"""Copy a frozen SQLite snapshot into an empty, migrated PostgreSQL database.

No deletes, external provider calls or workflow transitions. IDs, timestamps and
contact history are copied explicitly; a retry is a no-op only for identical data.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    func,
    insert,
    inspect,
    select,
    text,
)
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine
from sqlalchemy.pool import NullPool

from app.db import models as _models  # noqa: F401
from app.db.base import Base


class DatabaseMigrationError(RuntimeError):
    pass


@dataclass
class Snapshot:
    revision: str
    rows: dict[str, list[dict]]
    fingerprints: dict[str, dict]


def canonical(value):
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.replace(tzinfo=value.tzinfo or UTC).astimezone(UTC).isoformat(timespec="microseconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value.normalize()) if value else "0"
    if isinstance(value, bytes):
        return {"bytes": value.hex()}
    if isinstance(value, dict):
        return {str(k): canonical(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [canonical(v) for v in value]
    return value


def fingerprint(table, rows) -> dict:
    # Sort in Python so database collation does not change the comparison order.
    encoded = sorted(json.dumps(
        [canonical(row[c.name]) for c in table.columns], ensure_ascii=False,
        sort_keys=True, separators=(",", ":"), allow_nan=False,
    ) for row in rows)
    digest = hashlib.sha256()
    for row in encoded:
        digest.update(row.encode("utf-8"))
        digest.update(b"\n")
    return {"count": len(encoded), "sha256": digest.hexdigest()}


def load_snapshot(path: Path) -> Snapshot:
    path = path.resolve(strict=True)
    engine = create_engine(
        "sqlite://", creator=lambda: sqlite3.connect(path.as_uri() + "?mode=ro", uri=True),
        poolclass=NullPool,
    )
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("BEGIN")
            if connection.exec_driver_sql("PRAGMA integrity_check").scalar() != "ok":
                raise DatabaseMigrationError("Snapshot integrity check failed")
            if connection.exec_driver_sql("PRAGMA foreign_key_check").first() is not None:
                raise DatabaseMigrationError("Snapshot has foreign key violations")
            expected = set(Base.metadata.tables) | {"alembic_version"}
            if set(inspect(connection).get_table_names()) != expected:
                raise DatabaseMigrationError("Snapshot contains an unexpected table set")
            revisions = connection.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
            if len(revisions) != 1:
                raise DatabaseMigrationError("Snapshot must have exactly one Alembic revision")
            rows = {t.name: [dict(r) for r in connection.execute(select(t)).mappings()]
                    for t in Base.metadata.sorted_tables}
            hashes = {t.name: fingerprint(t, rows[t.name]) for t in Base.metadata.sorted_tables}
            return Snapshot(revisions[0], rows, hashes)
    finally:
        engine.dispose()


async def target_fingerprints(connection: AsyncConnection) -> dict:
    return {t.name: fingerprint(t, (await connection.execute(select(t))).mappings().all())
            for t in Base.metadata.sorted_tables}


async def _repair_sequences(connection: AsyncConnection) -> int:
    if connection.dialect.name != "postgresql":
        return 0
    repaired = 0
    preparer = connection.dialect.identifier_preparer
    for table in Base.metadata.sorted_tables:
        for column in table.primary_key.columns:
            if not isinstance(column.type, Integer):
                continue
            sequence = await connection.scalar(
                select(func.pg_get_serial_sequence(table.name, column.name))
            )
            maximum = await connection.scalar(select(func.max(column)))
            if not sequence or maximum is None:
                continue
            qualified = ".".join(preparer.quote(part) for part in sequence.split("."))
            last, called = (await connection.execute(text(f"SELECT last_value, is_called FROM {qualified}"))).one()
            if last < maximum or (last == maximum and not called):
                await connection.execute(select(func.setval(sequence, maximum, True)))
                repaired += 1
    return repaired


async def _copy_in_transaction(snapshot: Snapshot, connection: AsyncConnection) -> dict:
    if connection.dialect.name == "postgresql":
        await connection.execute(select(func.pg_advisory_xact_lock(0x4C5241444D494752)))
    revisions = (await connection.execute(text("SELECT version_num FROM alembic_version"))).scalars().all()
    if revisions != [snapshot.revision]:
        raise DatabaseMigrationError("Source and target Alembic revisions differ")
    actual_tables = await connection.run_sync(lambda c: set(inspect(c).get_table_names()))
    if actual_tables != set(Base.metadata.tables) | {"alembic_version"}:
        raise DatabaseMigrationError("Target contains an unexpected table set")
    current = await target_fingerprints(connection)
    if any(item["count"] for item in current.values()):
        if current != snapshot.fingerprints:
            raise DatabaseMigrationError("Target is not empty and differs from the snapshot; nothing was overwritten")
        return {"copied": False, "sequences_repaired": await _repair_sequences(connection), "tables": current}
    for table in Base.metadata.sorted_tables:
        rows = []
        for original in snapshot.rows[table.name]:
            row = dict(original)
            for column in table.columns:
                value = row[column.name]
                if isinstance(column.type, DateTime) and column.type.timezone and isinstance(value, datetime) and value.tzinfo is None:
                    row[column.name] = value.replace(tzinfo=UTC)
            rows.append(row)
        for start in range(0, len(rows), 100):
            await connection.execute(insert(table), rows[start:start + 100])
    actual = await target_fingerprints(connection)
    if actual != snapshot.fingerprints:
        raise DatabaseMigrationError("Target data verification failed; transaction rolled back")
    return {"copied": True, "sequences_repaired": await _repair_sequences(connection), "tables": actual}


def model_revision() -> str:
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    heads = ScriptDirectory.from_config(config).get_heads()
    if len(heads) != 1:
        raise DatabaseMigrationError("Migration code must have exactly one head")
    return heads[0]


async def _initialize_empty_target(connection: AsyncConnection, revision: str) -> None:
    # Historical migrations seed configuration rows. Build the current schema
    # directly for a full snapshot restore, so those seeds cannot replace history.
    # Never clear an existing schema, even when its tables contain no rows.
    tables = await connection.run_sync(lambda c: inspect(c).get_table_names())
    if tables:
        raise DatabaseMigrationError("Initialization requires a database with no tables")
    await connection.run_sync(Base.metadata.create_all)
    version = Table("alembic_version", MetaData(), Column("version_num", String(32), primary_key=True))
    await connection.run_sync(version.create)
    await connection.execute(insert(version).values(version_num=revision))


async def copy_to_postgres(
    snapshot: Snapshot, engine: AsyncEngine, *, initialize: bool = False,
) -> dict:
    if engine.dialect.name != "postgresql":
        raise DatabaseMigrationError("Migration target must be PostgreSQL")
    if "-pooler" in (engine.url.host or ""):
        raise DatabaseMigrationError("Use a direct connection for database migration")
    if initialize and snapshot.revision != model_revision():
        raise DatabaseMigrationError("Upgrade a working snapshot copy to the current code head first")
    async with engine.begin() as connection:
        if initialize:
            await connection.execute(select(func.pg_advisory_xact_lock(0x4C5241444D494752)))
            await _initialize_empty_target(connection, snapshot.revision)
        return await _copy_in_transaction(snapshot, connection)
