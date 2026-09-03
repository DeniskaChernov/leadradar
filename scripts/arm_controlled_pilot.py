"""Arm controlled pilot after authoritative preflight PASS.

Does NOT enable OpenAI. Does NOT start a live scan.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import select, update  # noqa: E402

from app.config import get_settings, normalize_instagram_handle  # noqa: E402
from app.db.models import Competitor  # noqa: E402
from app.db.session import create_engine, create_session_factory  # noqa: E402
from app.services.operational_control_service import OperationalControlService  # noqa: E402
from app.services.pilot_readiness_service import (  # noqa: E402
    MAX_PILOT_CREDITS,
    MIN_PILOT_CREDITS,
    PilotReadinessService,
)

DEFAULT_CREDITS = 5


async def arm(*, competitor: str, credits: int) -> int:
    settings = get_settings()
    engine = create_engine(settings)
    factory = create_session_factory(engine)
    ops = OperationalControlService(factory)
    await ops.load()
    normalized = normalize_instagram_handle(competitor)
    manager_id = settings.web_manager_id or 1

    try:
        readiness = await PilotReadinessService(factory, settings).evaluate(
            competitor_handle=normalized,
            scan_credits=credits,
        )
        if not readiness.ready:
            print("arm_controlled_pilot: PREFLIGHT FAIL — no DB mutations")
            for item in readiness.blocking_reasons:
                print(f"  [X] {item}")
            return 1

        async with factory() as session:
            await session.execute(
                update(Competitor)
                .where(Competitor.normalized_handle != normalized)
                .values(active=False)
            )
            activated = await session.execute(
                update(Competitor)
                .where(Competitor.normalized_handle == normalized)
                .values(active=True)
            )
            if activated.rowcount != 1:
                await session.rollback()
                print(f"arm_controlled_pilot: failed to activate @{normalized}")
                return 1
            active = list(
                await session.scalars(
                    select(Competitor.normalized_handle).where(Competitor.active.is_(True))
                )
            )
            if active != [normalized]:
                await session.rollback()
                print(
                    "arm_controlled_pilot: active set is not exactly one competitor "
                    f"after pause/activate: {active}"
                )
                return 1
            await session.commit()

        # OpenAI НЕ включаем — только Radar после проверки active==1.
        snap = await ops.set_radar_live(
            True,
            manager_id=manager_id,
            default_scan_credits=credits,
        )
        if not snap.radar_live_armed:
            print("arm_controlled_pilot: Radar arm failed — leaving Radar OFF")
            return 1
        if snap.openai_live_armed:
            # Fail-safe: никогда не оставляем OpenAI ON из этого скрипта.
            await ops.set_openai_live(False, manager_id=manager_id)
            print("arm_controlled_pilot: forced OpenAI OFF (must stay rules-only)")

        final = ops.snapshot()
        print(
            "arm_controlled_pilot: OK",
            f"active=@{normalized}",
            f"radar={final.radar_live_armed}",
            f"openai={final.openai_live_armed}",
            f"default_credits={final.default_scan_credits}",
        )
        if final.openai_live_armed:
            print("arm_controlled_pilot: ERROR openai still armed")
            return 1
        return 0
    finally:
        await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description="Arm controlled pilot (no OpenAI, no scan)")
    parser.add_argument("--competitor", required=True, help="Instagram handle")
    parser.add_argument(
        "--credits",
        type=int,
        default=DEFAULT_CREDITS,
        help=f"Scan cap {MIN_PILOT_CREDITS}..{MAX_PILOT_CREDITS}",
    )
    args = parser.parse_args()
    credits = int(args.credits)
    if credits < MIN_PILOT_CREDITS or credits > MAX_PILOT_CREDITS:
        print(f"credits must be in {MIN_PILOT_CREDITS}..{MAX_PILOT_CREDITS}")
        return 1
    return asyncio.run(arm(competitor=args.competitor, credits=credits))


if __name__ == "__main__":
    raise SystemExit(main())
