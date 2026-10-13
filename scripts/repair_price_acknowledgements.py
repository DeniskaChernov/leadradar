"""Preview/repair existing price thanks locally, without provider calls or Telegram sends."""

from __future__ import annotations

import argparse
import asyncio
import json

from app.config import get_settings
from app.db.session import create_engine, create_session_factory
from app.services.ai_service import RuleBasedLeadAnalyzer
from app.services.audience_service import AudienceEngine
from app.services.lead_service import LeadService


async def run(*, apply: bool = False) -> dict:
    settings = get_settings()
    engine = create_engine(settings)
    factory = create_session_factory(engine)
    service = LeadService(
        factory, RuleBasedLeadAnalyzer(), settings.hot_lead_threshold,
        audience_engine=AudienceEngine(factory, hot_threshold=settings.hot_lead_threshold),
        rules_version=settings.lead_analysis_version,
    )
    try:
        return await service.repair_price_acknowledgements(dry_run=not apply)
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Apply the local repair (default: preview)")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run(apply=args.apply)), ensure_ascii=False))


if __name__ == "__main__":
    main()
