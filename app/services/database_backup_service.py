"""Consistent SQLite snapshots and offline restoration under application ownership."""

from __future__ import annotations

import contextlib
import os
import shutil
import sqlite3
import tempfile
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.services.database_runtime_lock import (
    DatabaseRuntimeLock,
    DatabaseRuntimeOwnershipError,
    sqlite_database_path,
)


class DatabaseBackupError(RuntimeError):
    """A snapshot or restore was refused; connection details are never included."""


@dataclass(frozen=True, slots=True)
class RestoreResult:
    destination: Path
    recovery_copy: Path | None


def _different_files(source: Path, destination: Path) -> None:
    if source == destination or (
        destination.exists() and source.exists() and source.samefile(destination)
    ):
        raise DatabaseBackupError("Источник и назначение должны быть разными файлами.")


def _temporary_file(parent: Path, prefix: str) -> Path:
    parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=prefix, suffix=".tmp", dir=parent)
    os.close(descriptor)
    return Path(name)


def validate_sqlite_snapshot(path: Path, *, application_schema: bool = False) -> None:
    """Check the completed standalone snapshot, not a concurrently changing source."""
    try:
        with path.open("rb") as stream:
            if stream.read(16) != b"SQLite format 3\0":
                raise DatabaseBackupError("Файл не является корректной базой SQLite.")
        with contextlib.closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
            if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise DatabaseBackupError("Проверка целостности резервной копии не пройдена.")
            if db.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise DatabaseBackupError("В резервной копии нарушены связи данных.")
            if application_schema:
                required = {
                    "alembic_version",
                    "contacts",
                    "comments",
                    "leads",
                    "contact_events",
                    "cost_events",
                    "external_usage",
                }
                tables = {
                    row[0]
                    for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
                }
                if not required <= tables:
                    raise DatabaseBackupError("Копия не содержит обязательные таблицы Lead Radar.")
                revisions = db.execute("SELECT version_num FROM alembic_version").fetchall()
                if len(revisions) != 1:
                    raise DatabaseBackupError("В копии не подтверждена версия схемы Lead Radar.")
                from alembic.config import Config
                from alembic.script import ScriptDirectory

                root = Path(__file__).resolve().parents[2]
                config = Config(str(root / "alembic.ini"))
                config.set_main_option("script_location", str(root / "alembic"))
                try:
                    revision = ScriptDirectory.from_config(config).get_revision(revisions[0][0])
                    if revision is None or revision.revision != revisions[0][0]:
                        raise DatabaseBackupError("Неизвестная версия схемы резервной копии.")
                except DatabaseBackupError:
                    raise
                except Exception:
                    raise DatabaseBackupError("Неизвестная версия схемы резервной копии.") from None
    except DatabaseBackupError:
        raise
    except (OSError, sqlite3.Error):
        raise DatabaseBackupError(
            "Не удалось прочитать или проверить резервную копию SQLite."
        ) from None


def create_sqlite_snapshot(
    source: Path,
    destination: Path,
    *,
    application_schema: bool = False,
    timeout_seconds: float = 30,
) -> Path:
    """The SQLite backup API includes committed WAL pages and excludes uncommitted data.

    Publish only after validation and fsync. An incomplete copy never replaces
    the destination or causes old snapshots to be pruned.
    """
    source, destination = source.resolve(), destination.resolve()
    _different_files(source, destination)
    if not source.is_file() or source.stat().st_size == 0:
        raise DatabaseBackupError("Исходная база SQLite отсутствует или пуста.")
    temporary = _temporary_file(destination.parent, ".sqlite-snapshot-")
    deadline = time.monotonic() + timeout_seconds

    def progress(_status: int, _remaining: int, _total: int) -> None:
        if time.monotonic() > deadline:
            raise DatabaseBackupError("Истекло время создания копии: база занята или недоступна.")

    try:
        with contextlib.closing(
            sqlite3.connect(source.as_uri() + "?mode=ro", uri=True, timeout=1)
        ) as original:
            with contextlib.closing(sqlite3.connect(temporary)) as snapshot:
                original.backup(snapshot, pages=256, progress=progress, sleep=0.05)
                # Publish a standalone file even if the source uses WAL mode.
                snapshot.execute("PRAGMA journal_mode=DELETE")
        validate_sqlite_snapshot(temporary, application_schema=application_schema)
        with temporary.open("r+b") as stream:
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    except DatabaseBackupError:
        raise
    except (OSError, sqlite3.Error):
        raise DatabaseBackupError("Не удалось создать или опубликовать копию SQLite.") from None
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def _reject_sidecars(target: Path) -> None:
    if any(
        target.with_name(target.name + suffix).exists() for suffix in ("-wal", "-shm", "-journal")
    ):
        raise DatabaseBackupError(
            "У базы остались SQLite WAL/SHM/journal. Остановите все подключения и "
            "завершите штатное восстановление/checkpoint SQLite; не удаляйте журналы вручную."
        )


def _preserve_original(target: Path) -> Path | None:
    if not target.exists():
        return None
    if not target.is_file():
        raise DatabaseBackupError("Назначение восстановления не является файлом.")
    # Preserve even a corrupt original for investigation. It is deliberately
    # not named .db and is never offered as a validated restore candidate.
    directory = target.parent / ".backups"
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
    recovery = directory / f"pre-restore-{target.stem}-{stamp}-{uuid.uuid4().hex[:8]}.original"
    temporary = _temporary_file(directory, ".preserve-original-")
    try:
        with target.open("rb") as original, temporary.open("wb") as saved:
            shutil.copyfileobj(original, saved)
            saved.flush()
            os.fsync(saved.fileno())
        os.replace(temporary, recovery)
    finally:
        temporary.unlink(missing_ok=True)
    return recovery


def restore_sqlite_database(database_url: str, source: Path) -> RestoreResult:
    """--force in the CLI skips confirmation only; it never bypasses these guards.

    All Lead Radar processes must cooperate with DatabaseRuntimeLock. Other
    database tools must be closed before restoring; sidecars are rejected.
    """
    target = sqlite_database_path(database_url)
    if target is None:
        raise DatabaseBackupError("Восстановление поддерживает только файловую SQLite.")
    source = source.resolve()
    _different_files(source, target)
    try:
        with DatabaseRuntimeLock(database_url):
            _reject_sidecars(target)
            staged = _temporary_file(target.parent, ".sqlite-restore-")
            try:
                create_sqlite_snapshot(source, staged, application_schema=True)
                recovery = _preserve_original(target)
                _reject_sidecars(target)
                os.replace(staged, target)
            finally:
                staged.unlink(missing_ok=True)
    except DatabaseRuntimeOwnershipError:
        raise DatabaseBackupError(
            "Остановите Lead Radar: рабочая база занята или блокировка недоступна."
        ) from None
    except DatabaseBackupError:
        raise
    except OSError:
        raise DatabaseBackupError("Восстановление не завершено; исходный файл сохранён.") from None
    return RestoreResult(target, recovery)
