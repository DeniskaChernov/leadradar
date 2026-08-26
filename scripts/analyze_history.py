from __future__ import annotations

import argparse
import asyncio

from app.config import get_settings
from app.db.models import LeadStatus
from app.db.session import create_engine, create_session_factory, upgrade_database
from app.services.ai_service import (
    BudgetedCachedOpenAIAnalyzer,
    HybridLeadAnalyzer,
    OpenAILeadAnalyzer,
    RuleBasedLeadAnalyzer,
)
from app.services.lead_service import LeadService
from app.services.usage_service import ExternalUsageService


async def run(limit: int, allow_openai: bool) -> int:
    settings = get_settings()
    await upgrade_database()
    engine = create_engine(settings)
    try:
        session_factory = create_session_factory(engine)
        usage = ExternalUsageService(session_factory)
        openai = None
        if allow_openai:
            if not settings.openai_api_key:
                print("OpenAI не запущен: OPENAI_API_KEY не задан.")
            elif not settings.openai_live_enabled:
                print(
                    "OpenAI не запущен: нужен двойной предохранитель "
                    "OPENAI_LIVE_CALLS_ENABLED=true и EXTERNAL_LIVE_UNLOCK=ALLOW_EXTERNAL_CALLS."
                )
            else:
                openai = BudgetedCachedOpenAIAnalyzer(
                    OpenAILeadAnalyzer(settings.openai_api_key, settings.openai_model),
                    session_factory,
                    usage,
                    enabled=settings.openai_live_enabled,
                    daily_limit=settings.openai_daily_request_limit,
                )
        # Без --allow-openai ambiguous-сигналы не объявляются ошибочно "не лидами":
        # они переходят в AI_PENDING и ждут отдельного осознанного решения.
        analyzer = HybridLeadAnalyzer(
            RuleBasedLeadAnalyzer(),
            openai,
            mode="hybrid",
        )
        service = LeadService(session_factory, analyzer, settings.hot_lead_threshold)
        results = await service.backfill_unanalyzed_comments(limit)
        hot = sum(item.is_hot for item in results)
        rejected = sum(item.status == LeadStatus.NOT_LEAD for item in results)
        pending = sum(item.status == LeadStatus.AI_PENDING for item in results)
        print(f"Обработано: {len(results)} | горячих: {hot} | не лид: {rejected} | ждут AI: {pending}")
        print(
            "Режим:",
            "локальные правила + разрешённый OpenAI" if allow_openai else "только локальные правила, без токенов",
        )
        print("Исторический анализ не отправляет Telegram-уведомления.")
        return 0
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Разобрать уже сохранённые комментарии")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument(
        "--allow-openai",
        action="store_true",
        help="Разрешить OpenAI для неоднозначных сигналов. Требует OPENAI_LIVE_CALLS_ENABLED=true.",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(max(1, min(args.limit, 1000)), args.allow_openai)))


if __name__ == "__main__":
    main()
