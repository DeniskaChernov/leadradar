"""Тесты фоновой очереди разбора лидов."""

from datetime import UTC, datetime

from app.providers.mock import MockInstagramProvider
from app.schemas.instagram import InstagramComment
from app.services.contact_service import ContactService
from app.services.instagram_monitor import InstagramMonitor
from app.services.lead_analysis_pipeline import LeadAnalysisPipeline
from app.services.lead_service import LeadService
from tests.test_lead_service import StaticAnalyzer


class OrderedNotifier:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def notify_new_signal(self, lead_id: int) -> int:
        self.events.append(f"signal:{lead_id}")
        return 1

    async def notify_analyzed_lead(self, lead_id: int) -> int:
        self.events.append(f"analyzed:{lead_id}")
        return 0

    async def notify_hot_lead(self, lead_id: int) -> int:
        raise AssertionError("legacy hot-only path must not be used")

    async def flush_pending(self) -> int:
        return 0


class DelayedAnalyzer:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.inner = StaticAnalyzer()

    async def analyze(self, context):
        self.events.append("analysis")
        return await self.inner.analyze(context)


async def test_monitor_enqueues_analysis_without_blocking_cycle(session_factory):
    events: list[str] = []
    provider = MockInstagramProvider()
    notifier = OrderedNotifier(events)
    lead_service = LeadService(
        session_factory,
        DelayedAnalyzer(events),
        hot_threshold=70,
    )
    pipeline = LeadAnalysisPipeline(
        lead_service,
        notifier,
        max_concurrency=2,
        sync_mode=False,
    )
    await pipeline.start()
    monitor = InstagramMonitor(
        session_factory=session_factory,
        provider=provider,
        contact_service=ContactService(session_factory),
        lead_service=lead_service,
        notifier=notifier,
        competitors=["aiko.uz"],
        process_existing_comments=False,
        analysis_pipeline=pipeline,
    )
    await monitor.run_cycle()
    provider.add_comment(
        InstagramComment(
            platform_comment_id="async-queue-new",
            platform_user_id="async-queue-user",
            username="async_queue",
            display_name="Async Queue",
            profile_url="https://www.instagram.com/async_queue/",
            text="Narx qancha?",
            created_at=datetime.now(UTC),
        )
    )
    started = datetime.now(UTC)
    stats = await monitor.run_cycle()
    elapsed = (datetime.now(UTC) - started).total_seconds()
    assert elapsed < 2.0
    assert stats.leads_created == 1
    await pipeline.flush()
    assert events[0].startswith("signal:")
    assert "analysis" in events
    await pipeline.stop()


async def test_set_max_concurrency_hot_reload():
    events: list[str] = []

    class DummyLeadService:
        session_factory = None

        async def analyze_lead(self, lead_id: int):
            events.append(f"analyze:{lead_id}")
            return type("R", (), {
                "lead_id": lead_id,
                "is_hot": False,
                "significant_change_id": None,
            })()

    notifier = OrderedNotifier(events)
    service = DummyLeadService()
    pipeline = LeadAnalysisPipeline(service, notifier, max_concurrency=2, sync_mode=False)  # type: ignore[arg-type]
    await pipeline.start()
    await pipeline.set_max_concurrency(5)
    assert pipeline.max_concurrency == 5
    await pipeline.enqueue(1)
    await pipeline.flush()
    await pipeline.stop()
    assert "analyze:1" in events


async def test_sync_mode_pipeline_preserves_notification_order(session_factory):
    events: list[str] = []
    notifier = OrderedNotifier(events)
    lead_service = LeadService(session_factory, DelayedAnalyzer(events), hot_threshold=70)
    pipeline = LeadAnalysisPipeline(
        lead_service,
        notifier,
        sync_mode=True,
    )
    monitor = InstagramMonitor(
        session_factory=session_factory,
        provider=MockInstagramProvider(),
        contact_service=ContactService(session_factory),
        lead_service=lead_service,
        notifier=notifier,
        competitors=["aiko.uz"],
        process_existing_comments=False,
        analysis_pipeline=pipeline,
    )
    provider = monitor.provider
    await monitor.run_cycle()
    provider.add_comment(
        InstagramComment(
            platform_comment_id="sync-pipeline-new",
            platform_user_id="sync-pipeline-user",
            username="sync_pipe",
            display_name="Sync Pipe",
            profile_url="https://www.instagram.com/sync_pipe/",
            text="Buyurtma qilmoqchiman",
            created_at=datetime.now(UTC),
        )
    )
    await monitor.run_cycle()
    assert events[0].startswith("signal:")
    assert events.index("analysis") > events.index(events[0])
