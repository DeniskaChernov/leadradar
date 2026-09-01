# Арм controlled pilot: aiko.uz only, Radar 5 credits, OpenAI ON.
# не запускает live scan — только ops + пауза лишних источников.
from __future__ import annotations

import asyncio

from sqlalchemy import select, update

from app.config import get_settings
from app.db.models import Competitor
from app.db.session import create_engine, create_session_factory
from app.services.operational_control_service import OperationalControlService

PILOT_HANDLE = "aiko.uz"
DEFAULT_CREDITS = 5


async def main() -> None:
    settings = get_settings()
    engine = create_engine(settings)
    factory = create_session_factory(engine)
    ops = OperationalControlService(factory)
    await ops.load()

    async with factory() as session:
        paused = await session.execute(
            update(Competitor)
            .where(Competitor.normalized_handle != PILOT_HANDLE)
            .values(active=False)
        )
        activated = await session.execute(
            update(Competitor)
            .where(Competitor.normalized_handle == PILOT_HANDLE)
            .values(active=True)
        )
        active = (
            await session.scalars(
                select(Competitor.normalized_handle)
                .where(Competitor.active.is_(True))
                .order_by(Competitor.normalized_handle)
            )
        ).all()
        await session.commit()

    await ops.set_radar_live(
        True,
        manager_id=settings.web_manager_id or 1,
        default_scan_credits=DEFAULT_CREDITS,
    )
    await ops.set_openai_live(True, manager_id=settings.web_manager_id or 1)

    snap = ops.snapshot()
    print(
        "arm_controlled_pilot:",
        f"paused={paused.rowcount}",
        f"aiko_active={activated.rowcount}",
        f"active={list(active)}",
        f"radar={snap.radar_live_armed}",
        f"openai={snap.openai_live_armed}",
        f"default_credits={snap.default_scan_credits}",
    )
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
