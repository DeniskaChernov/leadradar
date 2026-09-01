# Восстановление мониторинга tier A после controlled pilot.
# Не трогает operational_controls и не удаляет данные.
from __future__ import annotations

import asyncio

from sqlalchemy import select, update

from app.config import get_settings
from app.db.models import Competitor
from app.db.session import create_engine, create_session_factory


async def main() -> None:
    settings = get_settings()
    engine = create_engine(settings)
    factory = create_session_factory(engine)

    async with factory() as session:
        restored = await session.execute(
            update(Competitor).where(Competitor.tier == "A").values(active=True)
        )
        active = (
            await session.scalars(
                select(Competitor.normalized_handle)
                .where(Competitor.active.is_(True))
                .order_by(Competitor.normalized_handle)
            )
        ).all()
        tier_a = (
            await session.scalars(
                select(Competitor.normalized_handle)
                .where(Competitor.tier == "A")
                .order_by(Competitor.normalized_handle)
            )
        ).all()
        await session.commit()

    print(
        "restore_tier_a_competitors:",
        f"restored={restored.rowcount}",
        f"tier_a={list(tier_a)}",
        f"active={list(active)}",
    )
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
