from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event, func, insert, select, text, update
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.ext.asyncio import create_async_engine

from app.db.base import Base
from app.db.models import Contact, ContactEvent, ContactEventType, Lead
from app.services.database_migration_service import (
    DatabaseMigrationError,
    _copy_in_transaction,
    _initialize_empty_target,
    canonical,
    copy_to_postgres,
    load_snapshot,
    model_revision,
    target_fingerprints,
)


@pytest.fixture
def snapshot_file(tmp_path):
    path = tmp_path / "snapshot.db"
    engine = create_engine("sqlite:///" + path.as_posix())
    with engine.begin() as c:
        Base.metadata.create_all(c)
        c.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)"))
        c.execute(text("INSERT INTO alembic_version VALUES ('unit-revision')"))
        c.execute(insert(Contact), [{
            "id": 17, "username": "unit", "normalized_username": "unit",
            "profile_url": "https://instagram.com/unit", "budget_from": Decimal("42.50"),
            "assigned_manager_telegram_id": 8_000_000_123,
            "display_name": "Мебель — плетёное кресло", "created_at": datetime(2026, 10, 20, 1, 2, 3, 456, UTC),
        }])
        c.execute(insert(ContactEvent), [{
            "id": 99, "contact_id": 17, "event_type": ContactEventType.NOTE_ADDED,
            "manager_telegram_id": 8_000_000_123,
            "payload_json": {"text": "Нархини айтинг\nбез изменений", "nested": [True, None, {"x": 1}]},
        }])
    engine.dispose()
    return path


async def target_schema(engine):
    async with engine.begin() as c:
        await c.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)"))
        await c.execute(text("INSERT INTO alembic_version VALUES ('unit-revision')"))


@pytest.mark.asyncio
async def test_copy_preserves_ids_history_unicode_and_is_idempotent(snapshot_file, session_factory):
    snapshot = load_snapshot(snapshot_file)
    engine = session_factory.kw["bind"]
    await target_schema(engine)
    async with engine.begin() as c:
        report = await _copy_in_transaction(snapshot, c)
    assert report["copied"] is True
    async with engine.begin() as c:
        repeated = await _copy_in_transaction(snapshot, c)
        assert await c.scalar(select(ContactEvent.id)) == 99
        assert await c.scalar(select(Contact.id)) == 17
        assert await c.scalar(select(ContactEvent.manager_telegram_id)) == 8_000_000_123
        assert await target_fingerprints(c) == snapshot.fingerprints
    assert repeated["copied"] is False


@pytest.mark.asyncio
async def test_different_existing_target_is_never_overwritten(snapshot_file, session_factory):
    snapshot = load_snapshot(snapshot_file)
    engine = session_factory.kw["bind"]
    await target_schema(engine)
    async with engine.begin() as c:
        await _copy_in_transaction(snapshot, c)
        await c.execute(update(Contact).values(display_name="Keep this target change"))
    with pytest.raises(DatabaseMigrationError, match="not empty"):
        async with engine.begin() as c:
            await _copy_in_transaction(snapshot, c)
    async with engine.connect() as c:
        assert await c.scalar(select(Contact.display_name)) == "Keep this target change"
        assert await c.scalar(select(func.count(ContactEvent.id))) == 1


@pytest.mark.asyncio
async def test_mid_copy_failure_rolls_back_all_inserted_rows(snapshot_file, session_factory):
    snapshot = load_snapshot(snapshot_file)
    engine = session_factory.kw["bind"]
    await target_schema(engine)

    def fail_history(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO contact_events"):
            raise RuntimeError("Injected interruption")

    event.listen(engine.sync_engine, "before_cursor_execute", fail_history)
    try:
        with pytest.raises(RuntimeError, match="Injected"):
            async with engine.begin() as c:
                await _copy_in_transaction(snapshot, c)
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", fail_history)
    async with engine.connect() as c:
        assert await c.scalar(select(func.count(Contact.id))) == 0
        assert await c.scalar(select(func.count(ContactEvent.id))) == 0
    async with engine.begin() as c:
        assert (await _copy_in_transaction(snapshot, c))["copied"] is True


@pytest.mark.asyncio
async def test_revision_mismatch_and_non_postgres_target_fail_closed(snapshot_file, session_factory):
    snapshot = load_snapshot(snapshot_file)
    engine = session_factory.kw["bind"]
    await target_schema(engine)
    async with engine.begin() as c:
        await c.execute(text("UPDATE alembic_version SET version_num='other-revision'"))
    with pytest.raises(DatabaseMigrationError, match="revisions differ"):
        async with engine.begin() as c:
            await _copy_in_transaction(snapshot, c)
    with pytest.raises(DatabaseMigrationError, match="must be PostgreSQL"):
        await copy_to_postgres(snapshot, engine)
    async with engine.connect() as c:
        assert await c.scalar(select(func.count(Contact.id))) == 0


def test_unknown_source_table_is_not_silently_dropped(snapshot_file):
    engine = create_engine("sqlite:///" + snapshot_file.as_posix())
    with engine.begin() as c:
        c.execute(text("CREATE TABLE unexpected_private_data (id INTEGER PRIMARY KEY)"))
    engine.dispose()
    with pytest.raises(DatabaseMigrationError, match="unexpected table"):
        load_snapshot(snapshot_file)


def test_canonical_datetime_money_and_json_comparison():
    naive = datetime(2026, 10, 20, 5)
    shifted = datetime(2026, 10, 20, 10, tzinfo=timezone(timedelta(hours=5)))
    assert canonical(naive) == canonical(shifted)
    assert canonical(Decimal("42.50")) == canonical(Decimal("42.5000"))
    assert canonical({"nested": [ContactEventType.CONTACTED]}) == {"nested": ["CONTACTED"]}


def test_telegram_id_columns_compile_to_bigint_on_postgres_and_preserve_sqlite_integer():
    columns = [c for t in Base.metadata.tables.values() for c in t.columns
               if c.name in {"assigned_manager_telegram_id", "manager_telegram_id", "chat_id",
                             "category_confirmed_by", "price_confirmed_by", "stock_confirmed_by",
                             "cogs_confirmed_by", "reviewed_by_manager_id"}]
    assert len(columns) >= 15
    assert all(c.type.compile(dialect=postgresql.dialect()) == "BIGINT" for c in columns)
    assert Contact.__table__.c.assigned_manager_telegram_id.type.compile(dialect=sqlite.dialect()) == "INTEGER"


def test_postgres_keeps_existing_long_language_labels_without_rebuilding_sqlite():
    column = Lead.__table__.c.language
    assert column.type.compile(dialect=postgresql.dialect()) == "TEXT"
    assert column.type.compile(dialect=sqlite.dialect()) == "VARCHAR(16)"


@pytest.mark.asyncio
async def test_initialize_empty_database_then_restore_without_migration_seed_conflicts(snapshot_file):
    engine = create_async_engine("sqlite+aiosqlite://")
    snapshot = load_snapshot(snapshot_file)
    try:
        async with engine.begin() as c:
            await _initialize_empty_target(c, snapshot.revision)
            assert (await _copy_in_transaction(snapshot, c))["copied"] is True
        async with engine.begin() as c:
            assert (await _copy_in_transaction(snapshot, c))["copied"] is False
            with pytest.raises(DatabaseMigrationError, match="no tables"):
                await _initialize_empty_target(c, snapshot.revision)
        assert len(model_revision()) > 0
    finally:
        await engine.dispose()
