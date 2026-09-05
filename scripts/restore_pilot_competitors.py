# Восстановление мониторинга после controlled pilot.
# По умолчанию A+B (F1: качество > C-шум). Не трогает operational_controls.
from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select, update

from app.config import get_settings
from app.db.models import Competitor
from app.db.session import create_engine, create_session_factory

RESTORE_TIERS = ("A", "B", "C")
DEFAULT_RESTORE_TIERS = ("A", "B")


async def main(tiers: tuple[str, ...] = DEFAULT_RESTORE_TIERS) -> None:
    allowed = tuple(tier for tier in tiers if tier in RESTORE_TIERS)
    if not allowed:
        raise SystemExit("Укажите хотя бы один tier из A/B/C")
    settings = get_settings()
    engine = create_engine(settings)
    factory = create_session_factory(engine)

    async with factory() as session:
        restored = await session.execute(
            update(Competitor)
            .where(Competitor.tier.in_(allowed))
            .values(active=True)
        )
        by_tier: dict[str, list[str]] = {tier: [] for tier in allowed}
        rows = (
            await session.execute(
                select(Competitor.tier, Competitor.normalized_handle)
                .where(Competitor.active.is_(True))
                .order_by(Competitor.tier, Competitor.normalized_handle)
            )
        ).all()
        for tier, handle in rows:
            bucket = by_tier.setdefault(str(tier), [])
            bucket.append(handle)
        await session.commit()

    print(
        "restore_pilot_competitors:",
        f"tiers={list(allowed)}",
        f"restored={restored.rowcount}",
        f"by_tier={by_tier}",
    )
    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Restore competitor monitoring after pilot")
    parser.add_argument(
        "--tiers",
        default="A,B",
        help="Comma-separated tiers (default A,B). Use A,B,C for full restore.",
    )
    parser.add_argument(
        "--include-c",
        action="store_true",
        help="Shortcut for --tiers A,B,C",
    )
    args = parser.parse_args()
    if args.include_c:
        selected = RESTORE_TIERS
    else:
        selected = tuple(
            part.strip().upper()
            for part in str(args.tiers).split(",")
            if part.strip()
        ) or DEFAULT_RESTORE_TIERS
    asyncio.run(main(selected))
