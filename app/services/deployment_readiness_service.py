"""Offline deployment readiness: DB ping, Alembic head и drift без внешних вызовов."""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine

from alembic import command
from app.config import Settings
from app.db.models import ExternalBudgetReservation, ReservationStatus
from app.db.session import create_engine
from app.services.database_runtime_lock import sqlite_database_path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_ALEMBIC_CHECK_LOCK = threading.Lock()


@dataclass(frozen=True, slots=True)
class OfflineReadinessState:
    database_healthy: bool
    database_error: str | None
    migration_at_head: bool
    migration_drift_free: bool
    migration_error: str | None
    backup_present: bool
    uncertain_reservations: int

    @property
    def ready(self) -> bool:
        return self.database_healthy and self.migration_at_head and self.migration_drift_free

    @property
    def offline_blocks(self) -> tuple[str, ...]:
        blocks: list[str] = []
        if not self.database_healthy:
            blocks.append(f"Database health failed: {self.database_error or 'unknown error'}")
        if not self.migration_at_head:
            blocks.append(
                "Database migration is not at Alembic head: "
                f"{self.migration_error or 'unknown revision'}"
            )
        if not self.migration_drift_free:
            blocks.append(
                "ORM metadata has migration drift: "
                f"{self.migration_error or 'alembic check failed'}"
            )
        return tuple(blocks)


def alembic_config() -> Config:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    return config


def _check_migration_drift() -> None:
    # Alembic's module-level context cannot serve two command checks at once.
    # This lock runs in a worker thread and never blocks the HTTP event loop.
    with _ALEMBIC_CHECK_LOCK:
        command.check(alembic_config())


@lru_cache(maxsize=1)
def code_migration_heads() -> tuple[str, ...]:
    """A running build has immutable migration files; cache their expected head."""
    return tuple(ScriptDirectory.from_config(alembic_config()).get_heads())


async def inspect_runtime_readiness(session_factory, *, timeout_seconds: float = 3.0) -> dict:
    """Bounded platform probe; the full schema audit remains in /ready and CLI."""
    payload = {"ok": False, "database_healthy": False, "migration_at_head": False}
    try:
        async with asyncio.timeout(timeout_seconds):
            async with session_factory() as session:
                revisions = (await session.execute(text("SELECT version_num FROM alembic_version"))).scalars().all()
                payload["database_healthy"] = True
                heads = code_migration_heads()
                payload["migration_at_head"] = len(heads) == 1 and revisions == list(heads)
                payload["ok"] = payload["migration_at_head"]
    except Exception:
        # Public health responses must not disclose DSNs, SQL or exception text.
        pass
    return payload


def backup_present(settings: Settings) -> bool:
    if settings.database_url.startswith("sqlite"):
        source = sqlite_database_path(settings.database_url)
        if source is None:
            return False
        backups = (source.parent / ".backups").glob(f"{source.stem}-*{source.suffix or '.db'}")
        return any(path.is_file() and path.stat().st_size > 0 for path in backups)
    # PostgreSQL: never claim backup exists without an explicit restore-drill marker.
    marker = PROJECT_ROOT / ".runtime" / "postgres_backup_verified"
    return marker.is_file() and marker.stat().st_size > 0


async def inspect_offline_readiness(settings: Settings) -> OfflineReadinessState:
    """Проверить БД и миграции без обращения к провайдерам."""
    engine = create_engine(settings)
    try:
        return await _inspect_with_engine(settings, engine)
    finally:
        await engine.dispose()


async def _inspect_with_engine(settings: Settings, engine: AsyncEngine) -> OfflineReadinessState:
    database_healthy = False
    database_error: str | None = None
    migration_at_head = False
    migration_error: str | None = None
    uncertain_reservations = 0
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
            database_healthy = True

            def revision_state(sync_connection) -> tuple[str | None, tuple[str, ...]]:
                config = alembic_config()
                current = MigrationContext.configure(sync_connection).get_current_revision()
                heads = tuple(ScriptDirectory.from_config(config).get_heads())
                return current, heads

            current, heads = await connection.run_sync(revision_state)
            migration_at_head = current is not None and len(heads) == 1 and current == heads[0]
            if not migration_at_head:
                migration_error = f"current={current or 'none'}, heads={','.join(heads) or 'none'}"

            uncertain_reservations = int(
                await connection.scalar(
                    select(func.count(ExternalBudgetReservation.id)).where(
                        ExternalBudgetReservation.status == ReservationStatus.UNCERTAIN
                    )
                )
                or 0
            )
    except Exception as exc:
        database_error = f"{type(exc).__name__}: {exc}"

    migration_drift_free = False
    if database_healthy and migration_at_head:
        try:
            await asyncio.to_thread(_check_migration_drift)
            migration_drift_free = True
        except Exception as exc:
            migration_error = f"{type(exc).__name__}: {exc}"

    return OfflineReadinessState(
        database_healthy=database_healthy,
        database_error=database_error,
        migration_at_head=migration_at_head,
        migration_drift_free=migration_drift_free,
        migration_error=migration_error,
        backup_present=backup_present(settings),
        uncertain_reservations=uncertain_reservations,
    )
