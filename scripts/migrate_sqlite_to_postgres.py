"""Verify/copy an offline snapshot; target credentials are read from a private env file."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from dotenv import dotenv_values

from app.config import Settings
from app.db.session import create_engine
from app.services.database_migration_service import (
    DatabaseMigrationError,
    copy_to_postgres,
    load_snapshot,
)


def read_target_url(path: Path) -> str:
    env_path = path.resolve(strict=True)
    if env_path == Path(".env").resolve():
        raise DatabaseMigrationError("Use a separate private env file for the migration target")
    url = dotenv_values(env_path).get("DATABASE_URL")
    if not url:
        raise DatabaseMigrationError("Target env file has no DATABASE_URL")
    return url


async def migrate(args) -> dict:
    snapshot = await asyncio.to_thread(load_snapshot, args.snapshot)
    if not args.apply:
        return {"dry_run": True, "revision": snapshot.revision, "tables": snapshot.fingerprints}
    url = await asyncio.to_thread(read_target_url, args.env_file)
    engine = create_engine(Settings(_env_file=None, database_url=url))
    try:
        return await copy_to_postgres(snapshot, engine, initialize=args.initialize_target)
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--initialize-target", action="store_true",
                        help="Create the current schema only in a database with no tables")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if args.apply and not args.env_file:
        parser.error("--apply requires --env-file")
    if args.initialize_target and not args.apply:
        parser.error("--initialize-target requires --apply")
    try:
        result = asyncio.run(migrate(args))
    except DatabaseMigrationError as exc:
        raise SystemExit(str(exc)) from None
    except Exception as exc:
        # Driver exceptions can contain credentials, SQL values or private rows.
        raise SystemExit(f"Migration failed ({type(exc).__name__}); no requests were replayed") from None
    output = json.dumps(result, ensure_ascii=False, indent=2)
    if args.report:
        args.report.write_text(output, encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
