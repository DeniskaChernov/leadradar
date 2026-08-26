from datetime import UTC, datetime

from sqlalchemy import func, select

from app.db.models import Lead, LeadStatus, PublicSignal, PublicSignalStatus
from app.providers.mock import MockInstagramProvider
from app.schemas.instagram import InstagramComment
from app.services.ai_service import AIAnalysisError
from app.services.contact_service import ContactService
from app.services.instagram_monitor import InstagramMonitor
from app.services.lead_service import LeadService
from tests.test_lead_service import StaticAnalyzer


class OrderedNotifier:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.signal_ids: list[int] = []

    async def notify_new_signal(self, lead_id: int) -> int:
        self.events.append("notification")
        self.signal_ids.append(lead_id)
        return 1

    async def notify_analyzed_lead(self, lead_id: int) -> int:
        self.events.append("message_updated")
        return 0

    async def notify_hot_lead(self, lead_id: int) -> int:
        raise AssertionError("legacy hot-only notification path must not be used")

    async def flush_pending(self) -> int:
        return 0


class OrderedAnalyzer:
    def __init__(self, events: list[str], *, fail: bool = False) -> None:
        self.events = events
        self.fail = fail
        self.inner = StaticAnalyzer()

    async def analyze(self, context):
        self.events.append("analysis")
        assert "notification" in self.events
        if self.fail:
            raise AIAnalysisError("provider unavailable")
        return await self.inner.analyze(context)


async def _run_new_signal(session_factory, *, fail_analysis: bool = False):
    events: list[str] = []
    provider = MockInstagramProvider()
    notifier = OrderedNotifier(events)
    monitor = InstagramMonitor(
        session_factory=session_factory,
        provider=provider,
        contact_service=ContactService(session_factory),
        lead_service=LeadService(
            session_factory, OrderedAnalyzer(events, fail=fail_analysis), hot_threshold=70
        ),
        notifier=notifier,
        competitors=["aiko.uz"],
        process_existing_comments=False,
    )
    await monitor.run_cycle()
    provider.add_comment(
        InstagramComment(
            platform_comment_id="signal-first-new",
            platform_user_id="signal-first-user",
            username="signal_first",
            display_name="Signal First",
            profile_url="https://www.instagram.com/signal_first/",
            text="Narxi qancha?",
            created_at=datetime.now(UTC),
        )
    )
    stats = await monitor.run_cycle()
    return events, notifier, stats


async def test_new_comment_is_notified_before_analysis(session_factory):
    events, notifier, stats = await _run_new_signal(session_factory)

    assert events == ["notification", "analysis", "message_updated"]
    assert len(notifier.signal_ids) == 1
    assert stats.comments_created == 1
    assert stats.leads_created == 1
    async with session_factory() as session:
        signal = await session.scalar(
            select(PublicSignal).order_by(PublicSignal.id.desc()).limit(1)
        )
        lead = await session.scalar(select(Lead).where(Lead.id == notifier.signal_ids[0]))
        assert signal is not None and signal.status == PublicSignalStatus.ANALYZED
        assert lead is not None and lead.status == LeadStatus.NEW


async def test_ai_down_keeps_committed_signal_and_initial_notification(session_factory):
    events, notifier, _stats = await _run_new_signal(session_factory, fail_analysis=True)

    assert events == ["notification", "analysis", "message_updated"]
    assert len(notifier.signal_ids) == 1
    async with session_factory() as session:
        lead = await session.get(Lead, notifier.signal_ids[0])
        assert lead is not None and lead.status == LeadStatus.AI_PENDING
        assert await session.scalar(select(func.count(PublicSignal.id))) == 2
        failed = await session.scalar(
            select(PublicSignal).where(PublicSignal.comment_id == lead.comment_id)
        )
        assert failed is not None and failed.status == PublicSignalStatus.FAILED
