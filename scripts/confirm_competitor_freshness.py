"""Операторское подтверждение freshness конкурента без paid scan."""

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
from app.services.competitor_freshness_service import CompetitorFreshnessService  # noqa: E402


async def _run(handle: str) -> int:
    settings = get_settings()
    engine = create_engine(settings)
    factory = create_session_factory(engine)
    try:
        competitor = await CompetitorFreshnessService(factory).confirm_for_pilot(
            handle,
            manager_id=settings.web_manager_id,
        )
    except ValueError as exc:
        print(f"confirm_competitor_freshness: FAIL {exc}")
        return 1
    finally:
        await engine.dispose()
    print(
        "confirm_competitor_freshness: OK",
        f"@{competitor.normalized_handle}",
        f"status={competitor.freshness_status}",
        f"reason={competitor.freshness_reason}",
        f"manual_at={competitor.manual_freshness_confirmed_at}",
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Confirm competitor freshness for pilot")
    parser.add_argument("--competitor", required=True)
    args = parser.parse_args()
    return asyncio.run(_run(args.competitor))


if __name__ == "__main__":
    raise SystemExit(main())
