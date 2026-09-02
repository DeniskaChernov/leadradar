from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.db.models import Comment
from app.providers.mock import MockInstagramProvider
from app.schemas.instagram import InstagramComment
from app.services.contact_service import ContactService
from app.services.instagram_monitor import InstagramMonitor
from app.services.lead_service import LeadService
from tests.test_lead_service import StaticAnalyzer


class _Notifier:
    async def notify_hot_lead(self, lead_id: int) -> int:
        return 0

    async def flush_pending(self) -> int:
        return 0


async def test_monitor_skips_stale_comments(session_factory):
    provider = MockInstagramProvider()
    stale_at = datetime.now(UTC) - timedelta(days=120)
    provider._comments = [
        InstagramComment(
            platform_comment_id="mock-comment-stale",
            platform_user_id="mock-user-stale",
            username="stale_user",
            display_name="Stale",
            profile_url="https://www.instagram.com/stale_user/",
            text="eski narx?",
            created_at=stale_at,
        ),
        InstagramComment(
            platform_comment_id="mock-comment-fresh",
            platform_user_id="mock-user-fresh",
            username="fresh_user",
            display_name="Fresh",
            profile_url="https://www.instagram.com/fresh_user/",
            text="yangi narx?",
            created_at=datetime.now(UTC),
        ),
    ]
    monitor = InstagramMonitor(
        session_factory=session_factory,
        provider=provider,
        contact_service=ContactService(session_factory),
        lead_service=LeadService(
            session_factory,
            StaticAnalyzer(),
            hot_threshold=70,
            signal_max_age_days=30,
        ),
        notifier=_Notifier(),
        competitors=["aiko.uz"],
        process_existing_comments=False,
        max_signal_age_days=30,
    )

    stats = await monitor.run_cycle()

    assert stats.comments_skipped_stale == 1
    assert stats.comments_created == 1
    assert stats.leads_created == 0
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(Comment)) == 1
