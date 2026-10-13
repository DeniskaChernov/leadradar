"""Head probes remain timely while durable historical pagination is incomplete."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, update

from app.db.models import Comment, CoverageStatus, Lead, Post
from app.providers.budgeted import BudgetedInstagramProvider, ScanBudget, ScanBudgetExceededError
from app.providers.mock import MockInstagramProvider
from app.schemas.instagram import CommentFetchResult
from app.services.instagram_monitor import CycleStats
from app.services.usage_service import ExternalUsageService
from tests.conftest import seed_scrapecreators_instagram_policy
from tests.test_comment_capture_reliability import _monitor


class HistoricalPagesProvider(MockInstagramProvider):
    def __init__(self):
        super().__init__()
        self._post = self._post.model_copy(update={"comments_count": 100})
        self.cursors = []
        self.page_caps = []
        self.new_head = False
        self.failed_head = False
        self.finish_history = False
        self.finish_head = False

    async def get_comment_batch(self, post, *, cursor=None, max_pages=None, **kwargs):
        self.cursors.append(cursor)
        self.page_caps.append(max_pages)
        if cursor is None:
            comment_id = "fresh-head" if self.new_head else "first-head"
            next_cursor = "head-page-2" if self.new_head else "history-1"
        else:
            comment_id = f"old-{cursor}"
            next_cursor = (
                "history-1" if cursor == "head-page-2"
                else f"history-{int(cursor.split('-')[1]) + 1}"
            )
        comment = self._comments[0].model_copy(update={"platform_comment_id": comment_id})
        finished = (
            (self.finish_history and cursor is not None)
            or (self.finish_head and cursor is None)
        )
        return CommentFetchResult(
            comments=[comment], provider=self.name, pages_fetched=1,
            coverage_status="FULL" if finished else "PARTIAL",
            next_cursor=None if finished else next_cursor,
            cursor_exhausted=finished,
            fetch_error="ProviderResponseError" if self.failed_head and cursor is None else None,
        )


async def _first_scan(factory, *, existing=True):
    provider = HistoricalPagesProvider()
    monitor = _monitor(
        factory, provider, existing=existing, force_refresh_seconds=3600,
        baseline_max_comment_pages=1, incremental_max_comment_pages=1,
    )
    await monitor.run_cycle()
    return monitor, provider


@pytest.mark.parametrize("remote_count", [101, 99])
async def test_changed_remote_count_probes_head_before_saved_history(session_factory, remote_count):
    monitor, provider = await _first_scan(session_factory)
    provider.new_head = True
    provider._post = provider._post.model_copy(update={"comments_count": remote_count})
    stats = await monitor.run_cycle()
    assert stats.comments_created == stats.leads_created == 1
    assert provider.cursors == [None, None]
    async with session_factory() as session:
        post = await session.scalar(select(Post))
        assert post.comment_backfill_cursor == "history-1"
        assert post.last_synced_remote_count == remote_count
        assert post.coverage_status == CoverageStatus.PARTIAL
        assert await session.scalar(select(Comment.id).where(
            Comment.platform_comment_id == "fresh-head",
        )) is not None
    resumed = await monitor._prepare_post(provider._post)
    assert resumed.is_backfill
    assert resumed.comment_cursor == "history-1"
    assert not resumed.preserve_backfill_cursor


async def test_expired_head_probe_runs_even_when_remote_count_is_unchanged(session_factory):
    monitor, provider = await _first_scan(session_factory)
    provider.new_head = True
    async with session_factory() as session:
        await session.execute(update(Post).values(
            comments_checked_at=datetime.now(UTC) - timedelta(hours=2),
        ))
        await session.commit()
    stats = await monitor.run_cycle()
    assert stats.comments_created == 1
    assert provider.cursors == [None, None]
    async with session_factory() as session:
        post = await session.scalar(select(Post))
        assert post.comment_backfill_cursor == "history-1"
        assert post.comments_checked_at.replace(tzinfo=UTC) > datetime.now(UTC) - timedelta(minutes=1)


async def test_pure_backfill_does_not_refresh_head_timestamp_or_ack_remote_count(session_factory):
    monitor, provider = await _first_scan(session_factory)
    async with session_factory() as session:
        post = await session.scalar(select(Post))
        old_checked = post.comments_checked_at
    await monitor.run_cycle()
    assert provider.cursors == [None, "history-1"]
    async with session_factory() as session:
        post = await session.scalar(select(Post))
        assert post.comments_checked_at == old_checked
        assert post.last_synced_remote_count == 100
        assert post.comment_backfill_cursor == "history-2"


async def test_head_refresh_preserves_baseline_history_and_only_new_head_becomes_lead(
    session_factory,
):
    monitor, provider = await _first_scan(session_factory, existing=False)
    provider.new_head = True
    provider._post = provider._post.model_copy(update={"comments_count": 101})
    refreshed = await monitor.run_cycle()
    assert refreshed.leads_created == 1
    async with session_factory() as session:
        post = await session.scalar(select(Post))
        assert post.comment_backfill_is_baseline is True
        assert post.comment_backfill_provider == provider.comment_cursor_provider
    restarted = _monitor(
        session_factory, provider, existing=False, force_refresh_seconds=3600,
        baseline_max_comment_pages=1, incremental_max_comment_pages=1,
    )
    resumed = await restarted.run_cycle()
    assert resumed.comments_created == 1
    assert resumed.leads_created == 0
    assert provider.cursors == [None, None, "history-1"]
    async with session_factory() as session:
        assert await session.scalar(select(func.count(Lead.id))) == 1
        flags = dict((await session.execute(select(
            Comment.platform_comment_id, Comment.is_baseline,
        ))).all())
        assert flags == {"first-head": True, "fresh-head": False, "old-history-1": True}


async def test_damaged_head_refresh_keeps_saved_history_and_success_metadata(session_factory):
    monitor, provider = await _first_scan(session_factory)
    provider.new_head = provider.failed_head = True
    provider._post = provider._post.model_copy(update={"comments_count": 101})
    async with session_factory() as session:
        post = await session.scalar(select(Post))
        checked = post.comments_checked_at
    assert (await monitor.run_cycle()).errors == 1
    async with session_factory() as session:
        post = await session.scalar(select(Post))
        assert post.comment_backfill_cursor == "history-1"
        assert post.last_synced_remote_count == 100
        assert post.comments_checked_at == checked
        assert post.coverage_status == CoverageStatus.PARTIAL
    check = await monitor._prepare_post(provider._post)
    assert check.comment_cursor is None
    assert check.preserve_backfill_cursor


async def test_retained_backfill_forces_partial_even_if_stored_count_matches_metadata(
    session_factory,
):
    monitor, provider = await _first_scan(session_factory)
    provider.new_head = True
    provider.finish_head = True
    provider._post = provider._post.model_copy(update={"comments_count": 2})
    check = await monitor._prepare_post(provider._post)
    await monitor._process_prepared_reel(provider._post, check, CycleStats())
    async with session_factory() as session:
        post = await session.scalar(select(Post))
        assert post.comments_fetched_count == post.comments_count == 2
        assert post.comment_backfill_cursor == "history-1"
        assert post.coverage_status == CoverageStatus.PARTIAL
    provider.finish_history = True
    await monitor.run_cycle()
    async with session_factory() as session:
        post = await session.scalar(select(Post))
        assert post.comment_backfill_cursor is None
        assert post.coverage_status == CoverageStatus.FULL


async def test_head_and_history_keep_default_five_credit_and_two_page_caps(session_factory):
    await seed_scrapecreators_instagram_policy(session_factory)
    inner = HistoricalPagesProvider()
    inner.name = "scrapecreators"
    # Simulate public live metadata, rather than a locally generated demo post.
    inner._post = inner._post.model_copy(update={
        "platform_post_id": "3995171968259599771_2958485721",
        "url": "https://www.instagram.com/reel/DeH4Ac1tp2T/",
        "raw_data": {"source": "scrapecreators"},
    })
    budget = ScanBudget(default_limit=5)
    provider = BudgetedInstagramProvider(
        inner, ExternalUsageService(session_factory), enabled=True, daily_limit=100,
        scan_budget=budget,
    )
    monitor = _monitor(
        session_factory, provider, force_refresh_seconds=3600,
        incremental_max_comment_pages=2,
    )
    await monitor.run_cycle()
    assert budget.used == 3  # Discovery plus two historical comment pages.
    async with session_factory() as session:
        saved_cursor = (await session.scalar(select(Post))).comment_backfill_cursor
    inner.new_head = True
    inner._post = inner._post.model_copy(update={"comments_count": 101})
    refreshed = await monitor.run_cycle()
    assert budget.limit == 5
    assert budget.used == 3
    assert refreshed.comment_requests == 2
    assert inner.cursors == [None, "history-1", None, "head-page-2"]
    assert inner.page_caps == [1, 1, 1, 1]
    async with session_factory() as session:
        assert (await session.scalar(select(Post))).comment_backfill_cursor == saved_cursor
    resumed = await monitor.run_cycle()
    assert resumed.comment_requests == 2
    assert budget.used == 3
    assert inner.cursors[-2:] == [saved_cursor, "history-3"]


async def test_one_remaining_credit_fetches_head_and_preserves_history_without_extra_call(
    session_factory,
):
    await seed_scrapecreators_instagram_policy(session_factory)
    inner = HistoricalPagesProvider()
    inner.name = "scrapecreators"
    inner._post = inner._post.model_copy(update={
        "platform_post_id": "3995171968259599771_2958485721",
        "url": "https://www.instagram.com/reel/DeH4Ac1tp2T/",
        "raw_data": {"source": "scrapecreators"},
    })
    monitor = _monitor(session_factory, inner, force_refresh_seconds=3600)
    await monitor.run_cycle()
    budget = ScanBudget(default_limit=5, used=4)
    monitor.provider = BudgetedInstagramProvider(
        inner, ExternalUsageService(session_factory), enabled=True, daily_limit=100,
        scan_budget=budget,
    )
    inner.new_head = True
    inner._post = inner._post.model_copy(update={"comments_count": 101})
    check = await monitor._prepare_post(inner._post)
    stats = CycleStats()
    await monitor._process_prepared_reel(inner._post, check, stats)
    assert budget.used == budget.limit == 5
    assert stats.comment_requests == 1
    assert inner.cursors == [None, None]
    async with session_factory() as session:
        post = await session.scalar(select(Post))
        assert post.comment_backfill_cursor == "history-1"
        assert post.coverage_status == CoverageStatus.PARTIAL
    with pytest.raises(ScanBudgetExceededError):
        await monitor.provider.get_comment_batch(inner._post)
    assert inner.cursors == [None, None]
