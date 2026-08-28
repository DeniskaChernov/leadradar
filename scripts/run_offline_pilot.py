from __future__ import annotations

import argparse
import asyncio
import json
import tempfile
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.services.offline_pilot_service import OfflinePilotService


async def run(*, skip_ingestion: bool = False) -> dict:
    service = OfflinePilotService()
    cases = service.build_corpus()
    report = service.evaluate(cases)
    if not skip_ingestion:
        with tempfile.TemporaryDirectory(prefix="lead-radar-offline-pilot-") as temp_dir:
            database_path = Path(temp_dir) / "pilot.db"
            engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            session_factory = async_sessionmaker(engine, expire_on_commit=False)
            ingestion = await service.verify_ingestion_idempotency(session_factory, cases)
            await engine.dispose()
        report = service.with_ingestion(report, ingestion)
    return report.to_dict()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the deterministic network-free 500+ signal pilot gate."
    )
    parser.add_argument(
        "--skip-ingestion",
        action="store_true",
        help="Evaluate classifiers without the database idempotency replay.",
    )
    args = parser.parse_args()
    payload = asyncio.run(run(skip_ingestion=args.skip_ingestion))
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    raise SystemExit(0 if payload["passed"] else 1)


if __name__ == "__main__":
    main()
