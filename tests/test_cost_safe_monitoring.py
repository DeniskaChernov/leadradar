from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import select

from app.db.models import CoverageStatus, Post
from app.providers.base import InstagramProvider, ProviderCallUncertainError
from app.providers.budgeted import BudgetedInstagramProvider, ScanBudget
from app.providers.fallback import FallbackInstagramProvider
from app.providers.mock import MockInstagramProvider
from app.providers.scrapecreators import ScrapeCreatorsProvider
from app.schemas.instagram import (
    CommentFetchResult,
    InstagramComment,
    InstagramPost,
    InstagramProfile,
)
from app.services.contact_service import ContactService
from app.services.instagram_monitor import InstagramMonitor
from app.services.lead_service import LeadService
from app.services.usage_service import ExternalUsageService
from tests.test_lead_service import StaticAnalyzer
from tests.test_monitor import RecordingNotifier


class CountingMockProvider(MockInstagramProvider):
    def __init__(self) -> None:
        super().__init__()
        self.comment_batch_calls = 0
        self.max_pages_seen: list[int | None] = []

    async def get_comment_batch(
        self,
        post: InstagramPost,
        *,
        known_comment_ids: set[str] | None = None,
        max_pages: int | None = None,
        cursor: str | None = None,
    ) -> CommentFetchResult:
        self.comment_batch_calls += 1
        self.max_pages_seen.append(max_pages)
        return await super().get_comment_batch(
            post,
            known_comment_ids=known_comment_ids,
            max_pages=max_pages,
            cursor=cursor,
        )


async def test_zero_comments_never_calls_comments_api(session_factory):
    provider = CountingMockProvider()
    provider._comments = []
    provider._post = provider._post.model_copy(update={"comments_count": 0})
    monitor = InstagramMonitor(
        session_factory=session_factory,
        provider=provider,
        contact_service=ContactService(session_factory),
        lead_service=LeadService(session_factory, StaticAnalyzer(), hot_threshold=70),
        notifier=RecordingNotifier(),
        competitors=["aiko.uz"],
        process_existing_comments=False,
    )

    stats = await monitor.run_cycle()

    assert stats.comment_requests == 0
    assert stats.zero_comment_posts_skipped == 1
    assert stats.avoided_requests == 1
    assert provider.comment_batch_calls == 0
    async with session_factory() as session:
        post = await session.scalar(select(Post))
        assert post is not None
        assert post.coverage_status == CoverageStatus.FULL
        assert post.last_synced_remote_count == 0


async def test_baseline_and_incremental_use_small_page_limits(session_factory):
    provider = CountingMockProvider()
    monitor = InstagramMonitor(
        session_factory=session_factory,
        provider=provider,
        contact_service=ContactService(session_factory),
        lead_service=LeadService(session_factory, StaticAnalyzer(), hot_threshold=70),
        notifier=RecordingNotifier(),
        competitors=["aiko.uz"],
        process_existing_comments=False,
        baseline_max_comment_pages=1,
        incremental_max_comment_pages=2,
    )

    await monitor.run_cycle()
    provider.add_comment(
        InstagramComment(
            platform_comment_id="new-cost-safe-comment",
            platform_user_id="new-user",
            username="new_user",
            display_name="New User",
            profile_url="https://www.instagram.com/new_user/",
            text="narxi?",
            created_at=datetime.now(UTC),
        )
    )
    await monitor.run_cycle()

    assert provider.max_pages_seen == [1, 2]


@pytest.mark.asyncio
async def test_scrapecreators_stops_pagination_on_known_comment():
    requested_cursors: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        cursor = request.url.params.get("cursor")
        requested_cursors.append(cursor)
        if cursor is None:
            return httpx.Response(
                200,
                json={
                    "comments": [
                        {"id": "new-2", "text": "qancha?", "user": {"id": "u2", "username": "u2"}},
                        {"id": "known-1", "text": "old", "user": {"id": "u1", "username": "u1"}},
                    ],
                    "cursor": "page-2",
                },
            )
        return httpx.Response(
            200,
            json={
                "comments": [
                    {"id": "old-0", "text": "old", "user": {"id": "u0", "username": "u0"}}
                ],
                "cursor": None,
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = ScrapeCreatorsProvider("test-key", client=client, max_comment_pages=10)
    post = InstagramPost(
        platform_post_id="post-1",
        competitor="aiko.uz",
        url="https://www.instagram.com/reel/test/",
        comments_count=20,
    )
    try:
        result = await provider.get_comment_batch(
            post, known_comment_ids={"known-1"}, max_pages=5
        )
    finally:
        await client.aclose()

    assert result.pages_fetched == 1
    assert result.stopped_on_known_comment is True
    assert requested_cursors == [None]
    assert {item.platform_comment_id for item in result.comments} == {"new-2", "known-1"}


class ProfileProvider(InstagramProvider):
    def __init__(self, name: str, *, fail: bool) -> None:
        self.name = name
        self.fail = fail
        self.calls = 0

    async def get_profile(self, handle: str) -> InstagramProfile:
        self.calls += 1
        if self.fail:
            from app.providers.base import ProviderError

            raise ProviderError("temporary")
        return InstagramProfile(username=handle, profile_url=f"https://instagram.com/{handle}/")

    async def get_reels(self, handle: str) -> list[InstagramPost]:
        raise NotImplementedError

    async def get_post(self, url: str, competitor: str) -> InstagramPost:
        raise NotImplementedError

    async def get_comments(self, post: InstagramPost) -> list[InstagramComment]:
        raise NotImplementedError


class TwoPhaseProvider(InstagramProvider):
    name = "two-phase"

    def __init__(self) -> None:
        self.events: list[str] = []

    async def get_profile(self, handle: str) -> InstagramProfile:
        raise NotImplementedError

    async def get_reels(self, handle: str) -> list[InstagramPost]:
        self.events.append(f"reels:{handle}")
        return [
            InstagramPost(
                platform_post_id=f"post-{handle}",
                competitor=handle,
                url=f"https://www.instagram.com/reel/{handle}/",
                published_at=datetime.now(UTC),
                comments_count=1,
            )
        ]

    async def get_post(self, url: str, competitor: str) -> InstagramPost:
        raise NotImplementedError

    async def get_comments(self, post: InstagramPost) -> list[InstagramComment]:
        return []

    async def get_comment_batch(
        self,
        post: InstagramPost,
        *,
        known_comment_ids: set[str] | None = None,
        max_pages: int | None = None,
        cursor: str | None = None,
    ) -> CommentFetchResult:
        self.events.append(f"comments:{post.competitor}")
        return CommentFetchResult(
            comments=[],
            provider=self.name,
            pages_fetched=1,
            coverage_status="PARTIAL",
            cursor_exhausted=False,
        )


async def test_monitor_completes_discovery_phase_before_any_comment_refresh(
    session_factory,
):
    provider = TwoPhaseProvider()
    monitor = InstagramMonitor(
        session_factory=session_factory,
        provider=provider,
        contact_service=ContactService(session_factory),
        lead_service=LeadService(session_factory, StaticAnalyzer(), hot_threshold=70),
        notifier=RecordingNotifier(),
        competitors=["alpha.uz", "beta.uz"],
        process_existing_comments=False,
    )

    await monitor.run_cycle(force=True)

    assert provider.events[:2] == ["reels:alpha.uz", "reels:beta.uz"]
    assert all(event.startswith("comments:") for event in provider.events[2:])


async def test_fallback_cannot_bypass_one_unit_scan_budget(session_factory):
    from sqlalchemy import select

    from app.db.models import ExternalBudgetReservation, ReservationStatus
    from tests.conftest import seed_scrapecreators_instagram_policy

    await seed_scrapecreators_instagram_policy(session_factory)
    usage = ExternalUsageService(session_factory)
    shared = ScanBudget(default_limit=1)
    primary_inner = ProfileProvider("scrapecreators", fail=True)
    fallback_inner = ProfileProvider("brightdata", fail=False)
    primary = BudgetedInstagramProvider(
        primary_inner, usage, enabled=True, daily_limit=10, scan_budget=shared
    )
    fallback = BudgetedInstagramProvider(
        fallback_inner, usage, enabled=True, daily_limit=10, scan_budget=shared
    )
    provider = FallbackInstagramProvider(primary, fallback)
    provider.begin_cycle()

    with pytest.raises(ProviderCallUncertainError):
        await provider.get_profile("aiko.uz")

    assert primary_inner.calls == 1
    assert fallback_inner.calls == 0
    assert shared.used == 1
    # Started call without provider credit proof must not invent ExternalUsage rows.
    assert await usage.used_today("instagram") == 0
    assert await usage.active_reservations_today("instagram") == 1
    async with session_factory() as session:
        reservation = await session.scalar(select(ExternalBudgetReservation))
    assert reservation is not None
    assert reservation.status == ReservationStatus.UNCERTAIN
