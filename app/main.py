from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from app.bot.handlers import build_router
from app.config import Settings, get_settings
from app.db.session import create_engine, create_session_factory, init_database
from app.providers import create_instagram_provider
from app.services.ai_service import OpenAILeadAnalyzer, UnavailableLeadAnalyzer
from app.services.contact_service import ContactService
from app.services.instagram_monitor import InstagramMonitor
from app.services.lead_service import LeadService
from app.services.lead_workflow_service import LeadWorkflowService
from app.services.notification_service import NullLeadNotifier
from app.services.telegram_notification_service import TelegramLeadNotifier

logger = logging.getLogger(__name__)


async def run(*, once: bool = False) -> int:
    settings = get_settings()
    configure_logging(settings)
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    await init_database(engine)
    provider = create_instagram_provider(settings)
    analyzer = (
        OpenAILeadAnalyzer(settings.openai_api_key, settings.openai_model)
        if settings.openai_api_key
        else UnavailableLeadAnalyzer()
    )
    lead_service = LeadService(session_factory, analyzer, settings.hot_lead_threshold)
    workflow = LeadWorkflowService(session_factory, settings.hot_lead_threshold)

    if once:
        monitor = InstagramMonitor(
            session_factory=session_factory,
            provider=provider,
            contact_service=ContactService(session_factory),
            lead_service=lead_service,
            notifier=NullLeadNotifier(),
            competitors=settings.competitors,
            process_existing_comments=settings.process_existing_comments,
        )
        stats = await monitor.run_cycle()
        logger.info("one_shot_cycle_complete stats=%s", stats)
        await provider.aclose()
        await engine.dispose()
        return 0

    if not settings.telegram_bot_token:
        logger.error("TELEGRAM_BOT_TOKEN is not configured; application stopped safely")
        await provider.aclose()
        await engine.dispose()
        return 2

    bot = Bot(
        settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    notifier = TelegramLeadNotifier(
        bot, session_factory, workflow, settings.telegram_admin_chat_ids
    )
    monitor = InstagramMonitor(
        session_factory=session_factory,
        provider=provider,
        contact_service=ContactService(session_factory),
        lead_service=lead_service,
        notifier=notifier,
        competitors=settings.competitors,
        process_existing_comments=settings.process_existing_comments,
    )
    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher.include_router(build_router(settings, workflow, notifier))
    monitor_task = asyncio.create_task(_monitor_loop(monitor, settings))
    logger.info(
        "startup provider=%s competitors=%s interval_seconds=%s",
        provider.name,
        settings.competitors,
        settings.instagram_poll_interval_seconds,
    )
    try:
        await dispatcher.start_polling(bot)
    finally:
        monitor_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await monitor_task
        await provider.aclose()
        await bot.session.close()
        await engine.dispose()
    return 0


async def _monitor_loop(monitor: InstagramMonitor, settings: Settings) -> None:
    while True:
        try:
            stats = await monitor.run_cycle()
            logger.info("poll_cycle_complete stats=%s", stats)
        except Exception as exc:
            logger.exception("poll_cycle_failed error_type=%s", type(exc).__name__)
        await asyncio.sleep(settings.instagram_poll_interval_seconds)


def configure_logging(settings: Settings) -> None:
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Lead Radar local MVP")
    parser.add_argument("--once", action="store_true", help="Run one Instagram polling cycle")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(once=args.once)))


if __name__ == "__main__":
    main()

