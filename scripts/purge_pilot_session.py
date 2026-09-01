# Очистка артефактов controlled pilot / OpenAI smoke (2026-09-01).
# Лиды не удаляем (FK + contact_events); только AI ledger и пауза pilot-источников.
from __future__ import annotations

import asyncio

from sqlalchemy import delete, update

from app.config import get_settings
from app.db.models import AIRequest, Competitor, Lead
from app.db.session import create_engine, create_session_factory
from app.services.operational_control_service import OperationalControlService

PILOT_LEAD_IDS = (39, 40)
PILOT_COMPETITORS = ("chinar.uz", "mebel__house__")


async def main() -> None:
    settings = get_settings()
    engine = create_engine(settings)
    factory = create_session_factory(engine)
    ops = OperationalControlService(factory)
    await ops.load()

    async with factory() as session:
        ai_deleted = await session.execute(
            delete(AIRequest).where(AIRequest.lead_id.in_(PILOT_LEAD_IDS))
        )
        paused = await session.execute(
            update(Competitor)
            .where(Competitor.normalized_handle.in_(PILOT_COMPETITORS))
            .values(active=False)
        )
        await session.commit()

    await ops.set_radar_live(False, manager_id=settings.web_manager_id or 1)
    await ops.set_openai_live(True, manager_id=settings.web_manager_id or 1)

    remaining = []
    async with factory() as session:
        for lid in PILOT_LEAD_IDS:
            lead = await session.get(Lead, lid)
            if lead is not None:
                remaining.append(lid)

    print(
        "purge_pilot_session:",
        f"ai_requests={ai_deleted.rowcount}",
        f"competitors_paused={paused.rowcount}",
        f"pilot_leads_kept={remaining or 'none'}",
        f"openai_armed={ops.openai_live_armed()}",
        f"radar_armed={ops.radar_live_armed()}",
    )
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
