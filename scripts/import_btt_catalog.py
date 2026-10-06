"""Preview/apply a reviewed local BTT snapshot. Does not fetch or call external APIs."""

import argparse
import asyncio
import json
from pathlib import Path

from app.config import get_settings
from app.db.session import create_engine, create_session_factory
from app.services.product_catalog_service import ProductCatalogService
from app.services.public_catalog_import_service import import_btt_snapshot


async def run(snapshot_path: Path, *, apply: bool) -> None:
    settings = get_settings()
    manager_id = settings.web_manager_id or next(iter(settings.telegram_admin_chat_ids), 0)
    if apply and not manager_id:
        raise ValueError("Для журнала импорта нужен настроенный администратор")
    snapshot = json.loads(await asyncio.to_thread(snapshot_path.read_text, encoding="utf-8"))
    engine = create_engine(settings)
    try:
        result = await import_btt_snapshot(
            ProductCatalogService(create_session_factory(engine)), snapshot,
            manager_id=manager_id, apply=apply,
        )
        print(json.dumps(result, ensure_ascii=False))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, default=Path("app/data/btt_public_catalog_2026-10-06.json"))
    parser.add_argument("--apply", action="store_true")
    arguments = parser.parse_args()
    asyncio.run(run(arguments.snapshot, apply=arguments.apply))
