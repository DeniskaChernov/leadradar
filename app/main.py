from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging

import uvicorn
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from app.bot.handlers import build_router
from app.config import Settings, get_settings
from app.db.models import NotificationPolicy
from app.db.session import (
    backup_sqlite_database,
    create_engine,
    create_session_factory,
    upgrade_database,
)
from app.providers import create_instagram_provider
from app.services.ai_service import (
    BudgetedCachedOpenAIAnalyzer,
    HybridLeadAnalyzer,
    OpenAILeadAnalyzer,
    RuleBasedLeadAnalyzer,
    UnavailableLeadAnalyzer,
)
from app.services.audience_service import AudienceEngine
from app.services.contact_service import ContactService
from app.services.external_safety_recovery_service import ExternalSafetyRecoveryService
from app.services.instagram_monitor import InstagramMonitor
from app.services.lead_service import LeadService
from app.services.lead_workflow_service import LeadWorkflowService
from app.services.market_intelligence_service import MarketIntelligenceService
from app.services.meta_audience_service import MetaAudiencePlanningService
from app.services.monitor_controller import MonitorController
from app.services.monitor_run_service import MonitorRunService
from app.services.notification_service import NullLeadNotifier
from app.services.product_catalog_service import ProductCatalogService
from app.services.rattan_vertical_service import RattanVerticalService
from app.services.significant_change_service import SignificantChangeDetector
from app.services.telegram_notification_service import TelegramLeadNotifier
from app.services.usage_service import ExternalUsageService
from app.web.app import build_web_app
from app.web.queries import WebQueryService

logger = logging.getLogger(__name__)


async def run(*, once: bool = False, web_only: bool = False) -> int:
    settings = get_settings()
    backup = backup_sqlite_database(settings)
    if backup is not None:
        print(f"Database backup: {backup}")
    await upgrade_database()
    configure_logging(settings)
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    market_service = MarketIntelligenceService(session_factory)
    catalog_result = await market_service.sync_catalog()
    logger.info("market_catalog_synced result=%s", catalog_result)
    product_catalog_result = await ProductCatalogService(session_factory).sync_confirmed_catalog()
    logger.info("product_catalog_synced result=%s", product_catalog_result)
    rattan_result = await RattanVerticalService(session_factory).rebuild()
    logger.info("rattan_vertical_synced stats=%s", rattan_result)
    usage_service = ExternalUsageService(session_factory)
    recovery_stats = await ExternalSafetyRecoveryService(
        session_factory,
        usage_service,
        max_ai_attempts=settings.ai_request_max_attempts,
    ).recover()
    logger.info("external_safety_recovery_completed stats=%s", recovery_stats)
    provider = create_instagram_provider(settings, usage_service)
    rules = RuleBasedLeadAnalyzer()
    openai_analyzer = None
    if settings.openai_api_key:
        openai_analyzer = BudgetedCachedOpenAIAnalyzer(
            OpenAILeadAnalyzer(settings.openai_api_key, settings.openai_model),
            session_factory,
            usage_service,
            enabled=settings.openai_live_enabled,
            daily_limit=settings.openai_daily_request_limit,
            analysis_version=settings.lead_analysis_version,
            lease_seconds=settings.ai_request_lease_seconds,
            max_attempts=settings.ai_request_max_attempts,
        )
    analyzer = (
        HybridLeadAnalyzer(rules, openai_analyzer, mode=settings.ai_mode)
        if settings.ai_mode in {"rules", "hybrid", "openai"}
        else UnavailableLeadAnalyzer()
    )
    audience_engine = AudienceEngine(session_factory, settings.hot_lead_threshold)
    audience_contacts = await audience_engine.recalculate_all()
    logger.info("audience_engine_synced contacts=%s", audience_contacts)
    meta_plans = await MetaAudiencePlanningService(session_factory).sync_blueprints()
    logger.info("meta_audience_plans_synced changes=%s status=NOT_CONNECTED", meta_plans)
    change_detector = SignificantChangeDetector(
        session_factory, hot_threshold=settings.hot_lead_threshold
    )
    lead_service = LeadService(
        session_factory,
        analyzer,
        settings.hot_lead_threshold,
        audience_engine=audience_engine,
        change_detector=change_detector,
    )
    workflow = LeadWorkflowService(session_factory, settings.hot_lead_threshold)

    if once:
        if not settings.lead_search_enabled:
            logger.warning("lead_search_disabled trigger=once")
            await provider.aclose()
            await engine.dispose()
            return 2
        monitor = InstagramMonitor(
            session_factory=session_factory,
            provider=provider,
            contact_service=ContactService(session_factory),
            lead_service=lead_service,
            notifier=NullLeadNotifier(),
            competitors=settings.competitors,
            process_existing_comments=settings.process_existing_comments,
            force_refresh_seconds=settings.instagram_force_refresh_seconds,
            auto_repair_partial_coverage=settings.instagram_auto_repair_partial_coverage,
            baseline_max_comment_pages=settings.instagram_baseline_max_comment_pages,
            incremental_max_comment_pages=settings.instagram_incremental_max_comment_pages,
            analyze_baseline_comments=settings.analyze_baseline_comments,
            historical_analysis_batch_size=settings.historical_analysis_batch_size,
            retry_pending_enabled=settings.ai_pending_retry_enabled,
            retry_pending_batch_size=settings.ai_pending_retry_batch_size,
            retry_pending_cooldown_seconds=settings.ai_pending_retry_cooldown_seconds,
        )
        stats = await monitor.run_cycle(force=True)
        logger.info("one_shot_cycle_complete stats=%s", stats)
        await provider.aclose()
        await engine.dispose()
        return 0

    if web_only:
        if not settings.web_enabled:
            logger.error("WEB_ENABLED=false; web-only mode has nothing to start")
            await provider.aclose()
            await engine.dispose()
            return 2
        monitor = InstagramMonitor(
            session_factory=session_factory,
            provider=provider,
            contact_service=ContactService(session_factory),
            lead_service=lead_service,
            notifier=NullLeadNotifier(),
            competitors=settings.competitors,
            process_existing_comments=settings.process_existing_comments,
            force_refresh_seconds=settings.instagram_force_refresh_seconds,
            auto_repair_partial_coverage=settings.instagram_auto_repair_partial_coverage,
            baseline_max_comment_pages=settings.instagram_baseline_max_comment_pages,
            incremental_max_comment_pages=settings.instagram_incremental_max_comment_pages,
            analyze_baseline_comments=settings.analyze_baseline_comments,
            historical_analysis_batch_size=settings.historical_analysis_batch_size,
            retry_pending_enabled=settings.ai_pending_retry_enabled,
            retry_pending_batch_size=settings.ai_pending_retry_batch_size,
            retry_pending_cooldown_seconds=settings.ai_pending_retry_cooldown_seconds,
        )
        controller = MonitorController(monitor, MonitorRunService(session_factory, provider.name))
        web_app = build_web_app(
            settings,
            WebQueryService(session_factory, settings.hot_lead_threshold),
            workflow,
            controller,
            usage_service,
            lead_service,
        )
        web_server = uvicorn.Server(
            uvicorn.Config(
                web_app,
                host=settings.web_host,
                port=settings.web_port,
                log_level=settings.log_level.lower(),
                access_log=False,
            )
        )
        monitor_task = asyncio.create_task(_monitor_loop(controller, settings))
        logger.info("web_only_started url=http://%s:%s", settings.web_host, settings.web_port)
        try:
            await web_server.serve()
        finally:
            monitor_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await monitor_task
            await controller.stop()
            await provider.aclose()
            await engine.dispose()
        return 0

    if not settings.telegram_bot_token:
        logger.error(
            "TELEGRAM_BOT_TOKEN is not configured. Use --web-only for CRM testing without Telegram."
        )
        await provider.aclose()
        await engine.dispose()
        return 2

    bot = Bot(
        settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    notifier = TelegramLeadNotifier(
        bot,
        session_factory,
        workflow,
        settings.telegram_admin_chat_ids,
        hot_threshold=settings.hot_lead_threshold,
        max_attempts=settings.telegram_notification_max_attempts,
        lease_seconds=settings.telegram_notification_lease_seconds,
        notification_policy=NotificationPolicy(settings.notification_policy),
        delivery_enabled=settings.instagram_provider not in {"mock", "replay"},
    )
    monitor = InstagramMonitor(
        session_factory=session_factory,
        provider=provider,
        contact_service=ContactService(session_factory),
        lead_service=lead_service,
        notifier=notifier,
        competitors=settings.competitors,
        process_existing_comments=settings.process_existing_comments,
        force_refresh_seconds=settings.instagram_force_refresh_seconds,
        auto_repair_partial_coverage=settings.instagram_auto_repair_partial_coverage,
        baseline_max_comment_pages=settings.instagram_baseline_max_comment_pages,
        incremental_max_comment_pages=settings.instagram_incremental_max_comment_pages,
        analyze_baseline_comments=settings.analyze_baseline_comments,
        historical_analysis_batch_size=settings.historical_analysis_batch_size,
        retry_pending_enabled=settings.ai_pending_retry_enabled,
        retry_pending_batch_size=settings.ai_pending_retry_batch_size,
        retry_pending_cooldown_seconds=settings.ai_pending_retry_cooldown_seconds,
    )
    run_service = MonitorRunService(session_factory, provider.name)
    controller = MonitorController(monitor, run_service)
    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher.include_router(build_router(settings, workflow, notifier, controller))
    try:
        await _register_bot_commands(bot)
    except TelegramAPIError as exc:
        logger.warning("telegram_command_menu_failed error_type=%s", type(exc).__name__)
    monitor_task = asyncio.create_task(_monitor_loop(controller, settings))
    notification_task = asyncio.create_task(
        _notification_loop(notifier, settings), name="lead-radar-notifications"
    )
    web_task = None
    web_server = None
    if settings.web_enabled:
        web_app = build_web_app(
            settings,
            WebQueryService(session_factory, settings.hot_lead_threshold),
            workflow,
            controller,
            usage_service,
            lead_service,
            notification_worker_active=True,
        )
        web_config = uvicorn.Config(
            web_app,
            host=settings.web_host,
            port=settings.web_port,
            log_level=settings.log_level.lower(),
            access_log=False,
        )
        web_server = uvicorn.Server(web_config)
        web_task = asyncio.create_task(web_server.serve(), name="lead-radar-web")
        logger.info("web_dashboard_started url=http://%s:%s", settings.web_host, settings.web_port)
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
        notification_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await monitor_task
        with contextlib.suppress(asyncio.CancelledError):
            await notification_task
        if web_server is not None:
            web_server.should_exit = True
        if web_task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await web_task
        await controller.stop()
        await provider.aclose()
        await bot.session.close()
        await engine.dispose()
    return 0


async def _monitor_loop(controller: MonitorController, settings: Settings) -> None:
    while True:
        # Scheduled monitoring is opt-in. This prevents a plain UI/replay start from
        # mutating the main CRM database and prevents a live .env from spending credits
        # just because the application was opened. Manual scans stay available.
        if settings.lead_search_enabled and settings.monitor_schedule_enabled:
            live_provider = settings.instagram_provider not in {"mock", "replay"}
            scheduled_live_blocked = live_provider and settings.instagram_manual_live_scan_only
            if not scheduled_live_blocked and controller.start_cycle("schedule"):
                with contextlib.suppress(Exception):
                    await controller.wait_current()
        await asyncio.sleep(settings.instagram_poll_interval_seconds)


async def _notification_loop(notifier: TelegramLeadNotifier, settings: Settings) -> None:
    """Retry committed Telegram outbox rows even while lead search is paused."""
    while True:
        try:
            sent = await notifier.flush_pending()
            if sent:
                logger.info("telegram_notifications_flushed sent=%s", sent)
        except Exception as exc:
            logger.exception("telegram_notification_flush_failed error_type=%s", type(exc).__name__)
        await asyncio.sleep(settings.telegram_notification_flush_interval_seconds)


async def _register_bot_commands(bot: Bot) -> None:
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Открыть главное меню"),
            BotCommand(command="status", description="Состояние мониторинга"),
            BotCommand(command="stats", description="Статистика базы и сделок"),
            BotCommand(command="hot", description="Открытые HOT-лиды"),
            BotCommand(command="lead", description="Карточка лида по ID"),
            BotCommand(command="scan", description="Проверить Instagram сейчас"),
            BotCommand(command="competitors", description="Список конкурентов"),
            BotCommand(command="web", description="Открыть веб-интерфейс"),
            BotCommand(command="help", description="Справка по боту"),
            BotCommand(command="cancel", description="Отменить текущий диалог"),
        ]
    )


def configure_logging(settings: Settings) -> None:
    import os

    log_format = os.environ.get("LOG_FORMAT", "text").strip().lower()
    if log_format == "json":
        fmt = (
            '{"time":"%(asctime)s","level":"%(levelname)s",'
            '"logger":"%(name)s","message":"%(message)s"}'
        )
    else:
        fmt = "%(asctime)s %(levelname)s %(name)s %(message)s"
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format=fmt,
        force=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Lead Radar local MVP")
    parser.add_argument("--once", action="store_true", help="Run one Instagram polling cycle")
    parser.add_argument(
        "--web-only",
        action="store_true",
        help="Start only the local Mini App/CRM; Telegram token is not required",
    )
    args = parser.parse_args()
    if args.once and args.web_only:
        parser.error("--once and --web-only cannot be used together")
    try:
        exit_code = asyncio.run(run(once=args.once, web_only=args.web_only))
    except KeyboardInterrupt:
        logging.getLogger(__name__).info("shutdown_requested")
        exit_code = 0
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
