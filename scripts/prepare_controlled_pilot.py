"""Controlled Radar pilot preflight — authoritative fail-closed (NO LIVE)."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import get_settings  # noqa: E402
from app.db.session import create_engine, create_session_factory  # noqa: E402
from app.services.pilot_readiness_service import (  # noqa: E402
    MAX_PILOT_CREDITS,
    MIN_PILOT_CREDITS,
    PilotReadinessService,
)


async def _run(competitor: str | None, credits: int) -> int:
    settings = get_settings()
    engine = create_engine(settings)
    factory = create_session_factory(engine)
    try:
        result = await PilotReadinessService(factory, settings).evaluate(
            competitor_handle=competitor,
            scan_credits=credits,
        )
    finally:
        await engine.dispose()

    print("==================================================")
    print("  CONTROLLED RADAR PILOT — PREFLIGHT (NO LIVE)    ")
    print("==================================================")
    print(f"[i] competitor={competitor or '(not set)'} credits={credits}")
    snap = result.snapshot
    print(f"[{'OK' if snap.get('offline_ready') else 'X'}] Offline DB/migrations")
    print(f"[{'OK' if snap.get('backup_present') else 'X'}] Backup present")
    print(
        f"[{'OK' if not snap.get('uncertain_reservations') else 'X'}] "
        f"UNCERTAIN={snap.get('uncertain_reservations')}"
    )
    print(f"[{'OK' if snap.get('policy_present') else 'X'}] ProviderBudgetPolicy")
    print(f"[{'OK' if snap.get('wallet_present') else 'X'}] Wallet snapshot")
    print(
        f"[i] monthly_remaining={snap.get('monthly_remaining')} "
        f"balance={snap.get('credits_remaining')} "
        f"source={snap.get('credits_remaining_source')}"
    )
    print(f"[i] schedule={snap.get('monitor_schedule_enabled')} "
          f"manual_only={snap.get('instagram_manual_live_scan_only')}")
    print(f"[i] meta_live={snap.get('meta_ads_live_enabled')} "
          f"freshness={snap.get('freshness_status')}")
    print(f"[i] active_handles={snap.get('active_handles')}")

    if result.warnings:
        print("\nWARNINGS:")
        for item in result.warnings:
            print(f"  [!] {item}")
    if result.blocking_reasons:
        print("\nBLOCKERS:")
        for item in result.blocking_reasons:
            print(f"  [X] {item}")

    print("==================================================")
    if result.ready:
        print("RESULT: READY")
        return 0
    print("RESULT: NOT READY")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Controlled pilot preflight (no live)")
    parser.add_argument("--competitor", default="", help="Instagram handle for pilot")
    parser.add_argument(
        "--credits",
        type=int,
        default=5,
        help=f"Scan cap {MIN_PILOT_CREDITS}..{MAX_PILOT_CREDITS}",
    )
    args = parser.parse_args()
    return asyncio.run(_run(args.competitor.strip() or None, int(args.credits)))


if __name__ == "__main__":
    raise SystemExit(main())
