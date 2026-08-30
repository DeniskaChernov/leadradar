from sqlalchemy import text

from app.config import Settings
from app.db.models import MetaAudienceSync, MetaInterest, Product
from app.db.session import create_engine


async def test_sqlite_foreign_keys_are_enabled(tmp_path):
    database = tmp_path / "foreign-keys.db"
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{database.as_posix()}",
    )
    engine = create_engine(settings)
    try:
        async with engine.connect() as connection:
            assert await connection.scalar(text("PRAGMA foreign_keys")) == 1
    finally:
        await engine.dispose()


def test_schema_metadata_matches_named_unique_constraints():
    expected = {
        Product: {"uq_products_canonical_key", "uq_products_sku"},
        MetaInterest: {"uq_meta_interests_meta_interest_id"},
        MetaAudienceSync: {"uq_meta_audience_syncs_idempotency_key"},
    }

    for model, expected_names in expected.items():
        constraint_names = {
            constraint.name
            for constraint in model.__table__.constraints
            if constraint.name is not None
        }
        assert expected_names <= constraint_names

    assert Product.__table__.c.vertical.type.length == 32
