from __future__ import annotations

import asyncio

from app.config import get_settings
from app.db.session import create_engine, create_session_factory
from app.services.ai_service import HybridLeadAnalyzer, RuleBasedLeadAnalyzer
from app.services.lead_service import LeadService


async def run() -> int:
    settings = get_settings()
    engine = create_engine(settings)
    try:
        service = LeadService(
            create_session_factory(engine),
            HybridLeadAnalyzer(RuleBasedLeadAnalyzer(), None, mode="rules"),
            settings.hot_lead_threshold,
        )
        return await service.backfill_analysis_details()
    finally:
        await engine.dispose()


def main() -> None:
    updated = asyncio.run(run())
    print(f"Deep analysis rows enriched: {updated}")


if __name__ == "__main__":
    main()
