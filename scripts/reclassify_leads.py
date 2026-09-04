# CLI: переоценка свежих лидов новыми правилами (+ опционально GPT).
from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import func, select

from app.config import get_settings
from app.db.models import Lead, LeadStatus
from app.db.session import create_engine, create_session_factory
from app.providers import create_instagram_provider
from app.services.ai_service import (
    BudgetedCachedOpenAIAnalyzer,
    HybridLeadAnalyzer,
    OpenAILeadAnalyzer,
    RuleBasedLeadAnalyzer,
)
from app.services.lead_service import LeadService
from app.services.operational_control_service import OperationalControlService
from app.services.usage_service import ExternalUsageService


async def main() -> None:
    parser = argparse.ArgumentParser(description="Переоценить свежие лиды NEW/AI_PENDING")
    parser.add_argument("--limit", type=int, default=50, help="Сколько лидов обработать")
    args = parser.parse_args()

    get_settings.cache_clear()
    settings = get_settings()
    engine = create_engine(settings)
    factory = create_session_factory(engine)
    usage = ExternalUsageService(factory)
    ops = OperationalControlService(factory)
    await ops.load()
    snap = ops.snapshot()

    openai_ready = (
        settings.openai_live_enabled
        and bool(settings.openai_api_key)
        and snap.openai_live_armed
    )
    rules = RuleBasedLeadAnalyzer()
    openai_analyzer = None
    if openai_ready:
        openai_analyzer = BudgetedCachedOpenAIAnalyzer(
            OpenAILeadAnalyzer(settings.openai_api_key, settings.openai_model),
            factory,
            usage,
            enabled=settings.openai_live_enabled,
            daily_limit=settings.openai_daily_request_limit,
            analysis_version=settings.lead_analysis_version,
            lease_seconds=settings.ai_request_lease_seconds,
            max_attempts=settings.ai_request_max_attempts,
            live_gate=ops.openai_live_armed,
        )
    analyzer = HybridLeadAnalyzer(
        rules,
        openai_analyzer,
        mode=settings.ai_mode if openai_analyzer else "rules",
    )
    lead_service = LeadService(factory, analyzer, settings.hot_lead_threshold)

    async with factory() as session:
        before_not_lead = (
            await session.scalar(
                select(func.count()).select_from(Lead).where(Lead.status == LeadStatus.NOT_LEAD)
            )
        ) or 0

    results = await lead_service.reanalyze_batch(max(1, args.limit))
    not_lead = sum(item.status == LeadStatus.NOT_LEAD for item in results)
    still_new = sum(item.status == LeadStatus.NEW for item in results)
    pending = sum(item.status == LeadStatus.AI_PENDING for item in results)

    async with factory() as session:
        after_not_lead = (
            await session.scalar(
                select(func.count()).select_from(Lead).where(Lead.status == LeadStatus.NOT_LEAD)
            )
        ) or 0

    print(
        f"reclassify_leads: processed={len(results)} new={still_new} "
        f"not_lead={not_lead} not_lead_delta={after_not_lead - before_not_lead} pending={pending} "
        f"openai={openai_ready}"
    )
    provider = create_instagram_provider(settings, usage, live_gate=ops.radar_live_armed)
    await provider.aclose()
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
