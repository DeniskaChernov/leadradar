from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select, update

from app.db.models import Comment, ExternalBudgetReservation, Post
from app.providers.budgeted import BudgetedInstagramProvider, ScanBudget
from app.providers.fallback import FallbackInstagramProvider
from app.providers.mock import MockInstagramProvider
from app.providers.publication_origin import FixturePublicationError
from app.schemas.instagram import PostFetchResult
from app.services.usage_service import ExternalUsageService
from tests.test_comment_capture_reliability import _monitor


class LiveMetadataProvider(MockInstagramProvider):
    name = "scrapecreators"

    @property
    def supports_post_pagination(self):
        return True

    async def get_post_page(self, handle, *, cursor=None):
        return PostFetchResult(provider=self.name, coverage_status="FULL", cursor_exhausted=True)

    async def get_comment_batch(self, *args, **kwargs):
        raise AssertionError("Demo publication must not reach a live adapter")

    async def get_post(self, *args, **kwargs):
        raise AssertionError("Demo URL must not reach a live adapter")


@pytest.mark.parametrize("provider_name", ["scrapecreators", "brightdata"])
@pytest.mark.parametrize("origin", ["metadata", "id", "url"])
async def test_demo_post_is_rejected_before_any_budget_or_network_action(
    session_factory, provider_name, origin,
):
    inner = LiveMetadataProvider()
    inner.name = provider_name
    post = inner._post.model_copy(update={
        "platform_post_id": "3995171968259599771_2958485721",
        "url": "https://www.instagram.com/reel/DeH4Ac1tp2T/", "raw_data": {},
    })
    if origin == "metadata":
        post.raw_data = {"source": "mock"}
    elif origin == "id":
        post.platform_post_id = "mock-reel-001"
    else:
        post.url = "https://www.instagram.com/reel/mock-reel-001/"
    budget = ScanBudget(5)
    provider = BudgetedInstagramProvider(
        inner, ExternalUsageService(session_factory), enabled=True, daily_limit=100,
        scan_budget=budget,
    )
    with pytest.raises(FixturePublicationError, match="Тестовая публикация"):
        await provider.get_comment_batch(post)
    assert budget.used == 0
    async with session_factory() as session:
        assert await session.scalar(select(func.count(ExternalBudgetReservation.id))) == 0


async def test_demo_url_is_rejected_before_a_single_post_lookup(session_factory):
    provider = BudgetedInstagramProvider(
        LiveMetadataProvider(), ExternalUsageService(session_factory), enabled=True, daily_limit=100,
    )
    with pytest.raises(FixturePublicationError, match="Тестовая публикация"):
        await provider.get_post("https://www.instagram.com/reel/mock-reel-001/", "aiko.uz")
    async with session_factory() as session:
        assert await session.scalar(select(func.count(ExternalBudgetReservation.id))) == 0


async def test_fixture_rejection_does_not_activate_fallback(session_factory):
    primary = BudgetedInstagramProvider(
        LiveMetadataProvider(), ExternalUsageService(session_factory), enabled=True, daily_limit=100,
    )
    fallback = LiveMetadataProvider()
    # This unwrapped adapter raises AssertionError if fallback is attempted.
    provider = FallbackInstagramProvider(primary, fallback)
    with pytest.raises(FixturePublicationError):
        await provider.get_comment_batch(MockInstagramProvider()._post)
    async with session_factory() as session:
        assert await session.scalar(select(func.count(ExternalBudgetReservation.id))) == 0


async def test_saved_demo_is_skipped_without_failing_live_scan_or_deleting_history(session_factory):
    mock = MockInstagramProvider()
    await _monitor(session_factory, mock).run_cycle()
    async with session_factory() as session:
        await session.execute(update(Post).values(comments_checked_at=None))
        await session.commit()
    stats = await _monitor(session_factory, LiveMetadataProvider()).run_cycle()
    assert stats.fixture_posts_skipped == 1
    assert stats.saved_posts_resumed == stats.comment_requests == stats.errors == 0
    async with session_factory() as session:
        assert await session.scalar(select(func.count(Post.id))) == 1
        assert await session.scalar(select(func.count(Comment.id))) == 1


async def test_mock_workflow_still_accepts_its_own_demo_publication(session_factory):
    stats = await _monitor(session_factory, MockInstagramProvider()).run_cycle()
    assert stats.fixture_posts_skipped == 0
    assert stats.comment_requests == 1
    assert stats.comments_created == 1


async def test_fixture_marker_does_not_reject_a_real_publication(session_factory):
    inner = MockInstagramProvider()
    post = inner._post.model_copy(update={
        "platform_post_id": "3995171968259599771_2958485721",
        "url": "https://www.instagram.com/reel/DeH4Ac1tp2T/", "raw_data": {},
        "published_at": datetime.now(UTC),
    })
    from app.providers.publication_origin import is_fixture_publication
    assert not is_fixture_publication(post)
