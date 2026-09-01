# Восстановление мониторинга tier A/B/C после controlled pilot.
# Не трогает operational_controls и не удаляет данные.
from __future__ import annotations

import asyncio

from sqlalchemy import select, update

from app.config import get_settings
from app.db.models import Competitor
from app.db.session import create_engine, create_session_factory

RESTORE_TIERS = ("A", "B", "C")


async def main() -> None:
    settings = get_settings()
    engine = create_engine(settings)
    factory = create_session_factory(engine)

    async with factory() as session:
        restored = await session.execute(
            update(Competitor)
            .where(Competitor.tier.in_(RESTORE_TIERS))
            .values(active=True)
        )
        by_tier: dict[str, list[str]] = {tier: [] for tier in RESTORE_TIERS}
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
        f"restored={restored.rowcount}",
        f"by_tier={by_tier}",
    )
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
