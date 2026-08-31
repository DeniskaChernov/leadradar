"""Controlled Radar pilot preflight without live API calls.

Permanent checklist before a 5-10 credit manual scan.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import func, select  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db.models import Competitor, CostEvent, ProviderBudgetPolicy  # noqa: E402
from app.db.session import create_engine, create_session_factory  # noqa: E402
from app.services.provider_credit_budget_service import (  # noqa: E402
    ProviderCreditBudgetService,
)
from scripts.live_readiness_check import evaluate_readiness, inspect_local_state  # noqa: E402


async def _snapshot() -> dict:
    settings = get_settings()
    engine = create_engine(settings)
    factory = create_session_factory(engine)
    try:
        async with factory() as session:
            competitor_count = await session.scalar(select(func.count(Competitor.id)))
            active_competitors = (
                await session.scalars(
                    select(Competitor.handle)
                    .where(Competitor.active.is_(True))
                    .order_by(Competitor.handle)
                    .limit(20)
                )
            ).all()
            policy = await session.scalar(
                select(ProviderBudgetPolicy).where(
                    ProviderBudgetPolicy.provider == "scrapecreators",
                    ProviderBudgetPolicy.service == "instagram",
                    ProviderBudgetPolicy.active.is_(True),
                )
            )
            cost_event_rows = int(
                await session.scalar(
                    select(func.count(CostEvent.id)).where(
                        CostEvent.provider == "scrapecreators",
                    )
                )
                or 0
            )
        wallet = await ProviderCreditBudgetService(factory).snapshot(
            provider="scrapecreators",
            service="instagram",
        )
        return {
            "settings": settings,
            "competitor_count": int(competitor_count or 0),
            "active_handles": list(active_competitors),
            "policy": policy,
            "wallet": wallet,
            "cost_event_rows": cost_event_rows,
        }
    finally:
        await engine.dispose()


def main() -> int:
    print("==================================================")
    print("  CONTROLLED RADAR PILOT — PREFLIGHT (NO LIVE)    ")
    print("==================================================")

    settings = get_settings()
    state = asyncio.run(inspect_local_state(settings))
    report = evaluate_readiness(settings, state)
    snap = asyncio.run(_snapshot())

    print(f"[{'OK' if report.offline_ready else 'X'}] Offline readiness")
    print(f"[{'OK' if report.live_ready else 'X'}] Live readiness (must unlock manually)")
    print(
        f"[i] Competitors total / active sample: "
        f"{snap['competitor_count']} / {len(snap['active_handles'])}"
    )
    for handle in snap["active_handles"][:5]:
        print(f"    - @{handle}")
    policy = snap["policy"]
    if policy is None:
        print("[X] ProviderBudgetPolicy scrapecreators/instagram missing")
    else:
        print(
            "[OK] Budget policy: "
            f"target={policy.monthly_target_units} soft={policy.monthly_soft_limit_units} "
            f"hard={policy.monthly_hard_limit_units} "
            f"default_scan={policy.default_scan_budget_units}"
        )
    wallet = snap["wallet"]
    if wallet is None:
        print("[X] Wallet snapshot unavailable (no policy)")
    else:
        print(
            f"[i] Wallet status={wallet.budget_status} "
            f"balance={wallet.credits_remaining} "
            f"month_remaining={wallet.monthly_remaining} "
            f"burn7={wallet.average_daily_burn_7d} burn30={wallet.average_daily_burn_30d}"
        )
    print(f"[i] CostEvent rows (scrapecreators): {snap['cost_event_rows']}")
    print(f"[i] MANUAL_LIVE_SCAN_ONLY={settings.instagram_manual_live_scan_only}")
    print(f"[i] MONITOR_SCHEDULE_ENABLED={settings.monitor_schedule_enabled}")
    print("[i] Meta live must stay OFF")

    print("\n--- Pilot contract (manual) ---")
    print("1. One active competitor; set others active=false for the pilot window.")
    print("2. MONITOR_SCHEDULE_ENABLED=false; manual scan only.")
    print("3. Cap 5-10 credits (not Deep 40).")
    print(
        "4. Compare: selected cap -> provider charged -> new comments "
        "-> commercial -> HOT -> errors."
    )
    print("5. After run: /economics coverage %, no UNCERTAIN, no hidden requests.")
    print("6. Do NOT enable Meta / Google live.")

    if report.offline_blocks:
        print("\nOFFLINE BLOCKS:")
        for item in report.offline_blocks:
            print(f"  [X] {item}")
    if report.live_blocks:
        print("\nLIVE BLOCKS (expected until explicit unlock):")
        for item in report.live_blocks:
            print(f"  [X] {item}")

    print("==================================================")
    if not report.offline_ready:
        print("RESULT: OFFLINE NOT READY - fix before pilot")
        return 1
    print("RESULT: OFFLINE READY - awaiting explicit live unlock + 5-10 credits")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
