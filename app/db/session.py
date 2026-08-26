from __future__ import annotations

import asyncio
import shutil
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

from alembic.config import Config
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from alembic import command
from app.config import Settings
from app.db.base import Base


def backup_sqlite_database(settings: Settings) -> Path | None:
    """Create a startup backup for local SQLite before migrations or writes.

    PostgreSQL/Railway is intentionally skipped because its backup strategy belongs to the
    managed database layer.
    """
    if not settings.database_backup_on_start:
        return None
    url = normalize_database_url(settings.database_url)
    prefix = "sqlite+aiosqlite:///"
    if not url.startswith(prefix):
        return None
    raw_path = url[len(prefix):]
    if raw_path in {"", ":memory:"}:
        return None
    source = Path(raw_path).expanduser()
    if not source.is_absolute():
        source = (Path.cwd() / source).resolve()
    if not source.exists() or source.stat().st_size == 0:
        return None
    backup_dir = source.parent / ".backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
    destination = backup_dir / f"{source.stem}-{stamp}{source.suffix or '.db'}"
    shutil.copy2(source, destination)
    backups = sorted(
        backup_dir.glob(f"{source.stem}-*{source.suffix or '.db'}"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    for old in backups[settings.database_backup_keep :]:
        old.unlink(missing_ok=True)
    return destination

def normalize_database_url(url: str) -> str:
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


def create_engine(settings: Settings) -> AsyncEngine:
    url = normalize_database_url(settings.database_url)
    connect_args = {"timeout": 30} if url.startswith("sqlite+") else {}
    engine = create_async_engine(url, pool_pre_ping=True, connect_args=connect_args)
    if url.startswith("sqlite+"):

        @event.listens_for(engine.sync_engine, "connect")
        def enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
    return engine


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


async def init_database(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def upgrade_database() -> None:
    await asyncio.to_thread(_upgrade_database_sync)


def _upgrade_database_sync() -> None:
    project_root = Path(__file__).resolve().parents[2]
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "alembic"))
    command.upgrade(config, "head")


async def session_scope(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
