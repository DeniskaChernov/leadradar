# Прогон AI_PENDING через hybrid+OpenAI (ops gate + дневной лимит должны быть открыты).
from __future__ import annotations

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
from app.services.audience_service import AudienceEngine
from app.services.lead_analysis_pipeline import LeadAnalysisPipeline
from app.services.lead_service import LeadService
from app.services.operational_control_service import OperationalControlService
from app.services.significant_change_service import SignificantChangeDetector
from app.services.usage_service import ExternalUsageService

DEFAULT_LIMIT = 50


async def main() -> None:
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
    budget = await usage.snapshot("openai", settings.openai_daily_request_limit)
    print(
        "flush_openai_pending:",
        f"openai_ready={openai_ready}",
        f"budget={budget.used_today}/{budget.daily_limit}",
        f"remaining={budget.remaining}",
    )
    if not openai_ready:
        print("ABORT: включите OpenAI live в Mini App и проверьте OPENAI_* в .env")
        await engine.dispose()
        return

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
    lead_service = LeadService(
        factory,
        HybridLeadAnalyzer(RuleBasedLeadAnalyzer(), openai_analyzer, mode=settings.ai_mode),
        settings.hot_lead_threshold,
        audience_engine=AudienceEngine(factory, settings.hot_lead_threshold),
        change_detector=SignificantChangeDetector(
            factory, hot_threshold=settings.hot_lead_threshold
        ),
    )

    class _NullNotifier:
        async def notify_hot_lead(self, _lead_id: int) -> int:
            return 0

    pipeline = LeadAnalysisPipeline(
        lead_service,
        _NullNotifier(),
        max_concurrency=snap.ai_analysis_max_concurrency,
    )
    await pipeline.start()

    pending_before = await lead_service.list_pending_lead_ids(DEFAULT_LIMIT, cooldown_seconds=0)
    queued = await pipeline.enqueue_retry_batch(DEFAULT_LIMIT, cooldown_seconds=0)
    print(f"pending_before={len(pending_before)} queued={queued}")
    await pipeline.flush()
    await pipeline.stop()

    async with factory() as session:
        pending_after = (
            await session.scalar(
                select(func.count())
                .select_from(Lead)
                .where(Lead.status == LeadStatus.AI_PENDING)
            )
        ) or 0
        openai_done = (
            await session.scalar(
                select(func.count())
                .select_from(Lead)
                .where(Lead.ai_source == "openai_or_cache")
            )
        ) or 0
    budget_after = await usage.snapshot("openai", settings.openai_daily_request_limit)
    print(
        "done:",
        f"pending_after={pending_after}",
        f"openai_total={openai_done}",
        f"budget={budget_after.used_today}/{budget_after.daily_limit}",
    )
    provider = create_instagram_provider(settings, usage, live_gate=ops.radar_live_armed)
    await provider.aclose()
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
