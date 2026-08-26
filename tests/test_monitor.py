from datetime import UTC, datetime

from sqlalchemy import func, select

from app.db.models import Comment, Contact, Lead
from app.providers.mock import MockInstagramProvider
from app.schemas.instagram import InstagramComment
from app.services.contact_service import ContactService
from app.services.instagram_monitor import InstagramMonitor
from app.services.lead_service import LeadService
from tests.test_lead_service import StaticAnalyzer


class RecordingNotifier:
    def __init__(self):
        self.lead_ids = []

    async def notify_hot_lead(self, lead_id: int) -> None:
        self.lead_ids.append(lead_id)


async def test_baseline_then_new_comment_creates_one_hot_lead(session_factory):
    provider = MockInstagramProvider()
    notifier = RecordingNotifier()
    monitor = InstagramMonitor(
        session_factory=session_factory,
        provider=provider,
        contact_service=ContactService(session_factory),
        lead_service=LeadService(session_factory, StaticAnalyzer(), hot_threshold=70),
        notifier=notifier,
        competitors=["aiko.uz"],
        process_existing_comments=False,
    )

    baseline = await monitor.run_cycle()
    provider.add_comment(
        InstagramComment(
            platform_comment_id="mock-comment-002",
            platform_user_id="mock-user-aziz-001",
            username="aziz_test",
            display_name="Aziz",
            profile_url="https://www.instagram.com/aziz_test/",
            text="narxi?",
            created_at=datetime.now(UTC),
        )
    )
    second = await monitor.run_cycle()
    unchanged = await monitor.run_cycle()

    assert baseline.comments_created == 1
    assert baseline.leads_created == 0
    assert second.comments_created == 1
    assert second.leads_created == 1
    assert second.hot_notifications == 1
    assert unchanged.comment_requests == 0
    assert len(notifier.lead_ids) == 1

    async with session_factory() as session:
        assert await session.scalar(select(func.count(Contact.id))) == 1
        assert await session.scalar(select(func.count(Comment.id))) == 2
        assert await session.scalar(select(func.count(Lead.id))) == 1


async def test_provider_change_rebuilds_baseline_without_leads(session_factory):
    first_provider = MockInstagramProvider()
    first_monitor = InstagramMonitor(
        session_factory=session_factory,
        provider=first_provider,
        contact_service=ContactService(session_factory),
        lead_service=LeadService(session_factory, StaticAnalyzer(), hot_threshold=70),
        notifier=RecordingNotifier(),
        competitors=["aiko.uz"],
        process_existing_comments=False,
    )
    await first_monitor.run_cycle()

    second_provider = MockInstagramProvider()
    second_provider.name = "scrapecreators+brightdata"
    second = await InstagramMonitor(
        session_factory=session_factory,
        provider=second_provider,
        contact_service=ContactService(session_factory),
        lead_service=LeadService(session_factory, StaticAnalyzer(), hot_threshold=70),
        notifier=RecordingNotifier(),
        competitors=["aiko.uz"],
        process_existing_comments=False,
    ).run_cycle()

    assert second.comment_requests == 1
    assert second.comments_created == 0
    assert second.leads_created == 0
    async with session_factory() as session:
        assert await session.scalar(select(func.count(Lead.id))) == 0
