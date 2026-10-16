"""Local SQLite lifecycle receipt; no credentials or exception text are retained."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path

from app.services.database_runtime_lock import sqlite_database_path

logger = logging.getLogger(__name__)
FIELDS = (
    "run_id",
    "pid",
    "mode",
    "state",
    "started_at",
    "heartbeat_at",
    "stopped_at",
    "exit_code",
    "error_type",
    "reason",
    "phase",
)


class RuntimeDiagnostics:
    """The caller holds DatabaseRuntimeLock until the final receipt is written.

    A previous RUNNING receipt means no final receipt was saved. It does not
    prove why the process stopped. Heartbeat is local liveness, not API readiness.
    PostgreSQL/memory runtimes have in-memory diagnostics only in this stage.
    """

    def __init__(self, database_url: str, mode: str) -> None:
        database = sqlite_database_path(database_url)
        self.path = (
            database.parent / ".runtime" / f"{database.name}.lifecycle.json" if database else None
        )
        self.data = {
            "build": "2026-10-16-presentation1",
            "run_id": uuid.uuid4().hex,
            "pid": os.getpid(),
            "mode": mode,
            "state": "RUNNING",
            "phase": "STARTUP",
            "started_at": datetime.now(UTC).isoformat(),
            "heartbeat_at": datetime.now(UTC).isoformat(),
            "stopped_at": None,
            "exit_code": None,
            "error_type": None,
            "reason": None,
        }
        self.previous: dict | None = None
        self.persisted = False

    def start(self) -> None:
        if self.path is not None and self.path.exists():
            try:
                if self.path.stat().st_size > 32_768:
                    raise ValueError("Oversized receipt")
                previous = json.loads(self.path.read_text(encoding="utf-8"))
                if not isinstance(previous, dict) or previous.get("state") not in {
                    "RUNNING",
                    "STOPPED",
                    "FAILED",
                    "INTERRUPTED",
                }:
                    raise ValueError("Invalid receipt")
                if (
                    not re.fullmatch(r"[a-f0-9]{32}", str(previous.get("run_id", "")))
                    or type(previous.get("pid")) is not int
                ):
                    raise ValueError("Invalid process identity")
                if previous.get("mode") not in {"once", "web-only", "full"} or previous.get(
                    "phase"
                ) not in {"STARTUP", "SERVING"}:
                    raise ValueError("Invalid runtime mode")
                for field in ("started_at", "heartbeat_at", "stopped_at"):
                    value = previous.get(field)
                    if value is None and field == "stopped_at":
                        continue
                    if (
                        not isinstance(value, str)
                        or len(value) > 64
                        or datetime.fromisoformat(value).tzinfo is None
                    ):
                        raise ValueError("Invalid timestamp")
                if previous.get("reason") not in {
                    None,
                    "cancellation",
                    "exception",
                    "nonzero_exit",
                    "completed",
                }:
                    raise ValueError("Invalid termination reason")
                if previous.get("error_type") is not None and (
                    not isinstance(previous["error_type"], str)
                    or not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]{0,127}", previous["error_type"])
                ):
                    raise ValueError("Invalid exception type")
                if previous.get("exit_code") is not None and type(previous["exit_code"]) is not int:
                    raise ValueError("Invalid exit code")
                self.previous = {key: previous.get(key) for key in FIELDS}
                self.previous["unfinished"] = previous["state"] == "RUNNING"
            except (OSError, TypeError, ValueError):
                self.previous = {"state": "UNREADABLE", "unfinished": None}
        self._write()
        logger.info(
            "runtime_started run_id=%s pid=%s mode=%s previous_state=%s",
            self.data["run_id"],
            self.data["pid"],
            self.data["mode"],
            (self.previous or {}).get("state", "NONE"),
        )

    def ready(self) -> None:
        if self.data["phase"] == "SERVING":
            return
        self.data["phase"] = "SERVING"
        self.touch()
        logger.info("runtime_serving run_id=%s pid=%s", self.data["run_id"], self.data["pid"])

    def touch(self) -> None:
        self.data["heartbeat_at"] = datetime.now(UTC).isoformat()
        self._write()

    async def heartbeat(self, *, interval: float = 30) -> None:
        while True:
            await asyncio.sleep(interval)
            self.touch()

    def finish(self, *, exit_code: int | None = None, error: BaseException | None = None) -> None:
        if isinstance(error, (asyncio.CancelledError, KeyboardInterrupt)):
            state, reason = "INTERRUPTED", "cancellation"
        elif error is not None:
            state, reason = "FAILED", "exception"
        elif exit_code:
            state, reason = "FAILED", "nonzero_exit"
        else:
            state, reason = "STOPPED", "completed"
        self.data.update(
            state=state,
            reason=reason,
            exit_code=exit_code,
            error_type=type(error).__name__ if error is not None else None,
            stopped_at=datetime.now(UTC).isoformat(),
        )
        self.touch()
        logger.info(
            "runtime_finished run_id=%s state=%s reason=%s exit_code=%s error_type=%s",
            self.data["run_id"],
            state,
            reason,
            exit_code,
            self.data["error_type"],
        )

    def snapshot(self) -> dict:
        return {
            **self.data,
            "previous": dict(self.previous) if self.previous is not None else None,
            "persisted": self.persisted,
            "persistent_supported": self.path is not None,
        }

    def display_snapshot(self) -> dict:
        result = self.snapshot()
        for item in (result, result.get("previous")):
            if item is None:
                continue
            for field in ("started_at", "heartbeat_at", "stopped_at"):
                value = item.get(field)
                try:
                    item[field] = datetime.fromisoformat(value) if isinstance(value, str) else None
                except ValueError:
                    item[field] = None
        return result

    def _write(self) -> None:
        if self.path is None:
            return
        temporary: Path | None = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                prefix=".lifecycle-",
                suffix=".tmp",
                dir=self.path.parent,
                delete=False,
            ) as stream:
                temporary = Path(stream.name)
                json.dump({**self.data, "previous": self.previous}, stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            self.persisted = True
        except OSError as exc:
            self.persisted = False
            logger.warning("runtime_receipt_write_failed error_type=%s", type(exc).__name__)
        finally:
            if temporary is not None:
                with contextlib.suppress(OSError):
                    temporary.unlink(missing_ok=True)
