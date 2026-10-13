# F1: синхронизация каталога + активация портфеля tier A/B без live spend.
# Не трогает kill-switch / EXTERNAL_LIVE_UNLOCK / operational_controls.
from __future__ import annotations

import argparse
import asyncio

from app.config import get_settings
from app.db.session import create_engine, create_session_factory
from app.services.market_intelligence_service import MarketIntelligenceService

DEFAULT_TIERS = ("A", "B")


async def _run(
    *, tiers: tuple[str, ...], catalog_managed_only: bool, sync: bool,
    handles: tuple[str, ...] | None = None, dry_run: bool = False,
) -> int:
    settings = get_settings()
    engine = create_engine(settings)
    factory = create_session_factory(engine)
    service = MarketIntelligenceService(factory)
    try:
        if sync and not dry_run:
            synced = await service.sync_catalog()
            print(
                "activate_source_portfolio sync:",
                f"created_competitors={synced['created_competitors']}",
                f"created_candidates={synced['created_candidates']}",
                f"promoted_candidates={synced['promoted_candidates']}",
            )
        result = await service.activate_portfolio(
            tiers=tiers,
            catalog_managed_only=catalog_managed_only,
            handles=handles,
            dry_run=dry_run,
        )
        print(
            "activate_source_portfolio:",
            f"tiers={result['tiers']}",
            f"scanned={result['scanned']}",
            f"activated={result['activated']}",
            f"already_active={result['already_active']}",
            f"handles={result['handles']}",
            f"dry_run={result['dry_run']}",
        )
        return 0
    finally:
        await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="F1: sync market catalog and activate IG source portfolio (DB only)"
    )
    parser.add_argument(
        "--tiers",
        default="A,B",
        help="Comma-separated tiers to activate (default A,B; add C only intentionally)",
    )
    parser.add_argument(
        "--include-manual",
        action="store_true",
        help="Also activate non-catalog_managed competitors in selected tiers",
    )
    parser.add_argument(
        "--no-sync",
        action="store_true",
        help="Skip catalog sync before activation",
    )
    parser.add_argument(
        "--handles", default=None,
        help="Activate only these registered Instagram handles (comma separated)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Preview existing sources without catalog sync or database writes",
    )
    args = parser.parse_args()
    tiers = tuple(
        part.strip().upper()
        for part in str(args.tiers).split(",")
        if part.strip()
    ) or DEFAULT_TIERS
    return asyncio.run(
        _run(
            tiers=tiers,
            catalog_managed_only=not args.include_manual,
            sync=not args.no_sync,
            handles=tuple(args.handles.split(",")) if args.handles is not None else None,
            dry_run=args.dry_run,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
