from sqlalchemy import text

from app.config import Settings
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
