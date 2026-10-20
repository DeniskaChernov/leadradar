"""Offline regressions for capture, public post coverage, and interrupted pagination."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import func, select, update

from app.db.models import (
    Comment,
    Competitor,
    CoverageStatus,
    ExternalBudgetReservation,
    Lead,
    Post,
    ReservationStatus,
)
from app.providers.base import (
    ProviderCallUncertainError,
    ProviderPrivacyError,
    ProviderResponseError,
)
from app.providers.budgeted import BudgetedInstagramProvider, ScanBudget
from app.providers.mock import MockInstagramProvider
from app.providers.scrapecreators import ScrapeCreatorsProvider
from app.schemas.instagram import CommentFetchResult, InstagramComment, InstagramPost
from app.services.contact_service import ContactService
from app.services.instagram_monitor import CycleStats, InstagramMonitor
from app.services.lead_service import LeadService
from app.services.usage_service import ExternalUsageService
from tests.conftest import seed_scrapecreators_instagram_policy
from tests.test_lead_service import StaticAnalyzer
from tests.test_monitor import RecordingNotifier


def _monitor(factory, provider, *, existing=True, **kwargs):
    return InstagramMonitor(
        session_factory=factory, provider=provider,
        contact_service=ContactService(factory),
        lead_service=LeadService(factory, StaticAnalyzer(), 70),
        notifier=RecordingNotifier(), competitors=["aiko.uz"],
        process_existing_comments=existing, **kwargs,
    )


def _post():
    return InstagramPost(
        platform_post_id="capture-post", competitor="aiko.uz",
        url="https://www.instagram.com/p/capture/", comments_count=2,
        published_at=datetime.now(UTC),
    )


def _comment_payload(comment_id):
    return {"id": comment_id, "text": "narxi?",
            "created_at": datetime.now(UTC).isoformat(),
            "user": {"id": f"user-{comment_id}", "username": f"user_{comment_id}"}}


@pytest.mark.parametrize("repair_partial", [False, True])
async def test_full_coverage_refreshes_after_interval_even_if_remote_count_is_unchanged(
    session_factory, repair_partial,
):
    provider = MockInstagramProvider()
    monitor = _monitor(session_factory, provider, force_refresh_seconds=3600,
                       auto_repair_partial_coverage=repair_partial)
    await monitor.run_cycle()
    async with session_factory() as session:
        await session.execute(update(Post).values(
            comments_checked_at=datetime.now(UTC) - timedelta(hours=2),
        ))
        await session.commit()
    # Instagram may remove one comment while another appears: same metadata count.
    provider._comments = [InstagramComment(
        platform_comment_id="replacement-comment", platform_user_id="replacement-user",
        username="replacement_user", profile_url="https://www.instagram.com/replacement_user/",
        text="qancha?", created_at=datetime.now(UTC),
    )]
    stats = await monitor.run_cycle()
    assert stats.comment_requests == 1
    assert stats.comments_created == 1
    async with session_factory() as session:
        assert await session.scalar(select(func.count(Lead.id))) == 2


@pytest.mark.parametrize("refresh_seconds", [0, 3600])
async def test_fresh_full_coverage_still_skips_unchanged_comments(session_factory, refresh_seconds):
    provider = MockInstagramProvider()
    monitor = _monitor(session_factory, provider, force_refresh_seconds=refresh_seconds)
    await monitor.run_cycle()
    assert (await monitor.run_cycle()).comment_requests == 0


async def test_known_comment_does_not_hide_new_comment_on_next_provider_page():
    cursors = []

    def handler(request):
        cursor = request.url.params.get("cursor")
        cursors.append(cursor)
        return httpx.Response(200, json={
            "comments": [_comment_payload("new" if cursor else "known")],
            "cursor": None if cursor else "next-page",
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = ScrapeCreatorsProvider("test", client=client)
        batch = await provider.get_comment_batch(_post(), known_comment_ids={"known"}, max_pages=2)
    assert cursors == [None, "next-page"]
    assert {item.platform_comment_id for item in batch.comments} == {"known", "new"}
    assert batch.cursor_exhausted
    assert not batch.stopped_on_known_comment


async def test_known_comment_keeps_cursor_when_one_page_cap_is_reached():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(
        200, json={"comments": [_comment_payload("known")], "cursor": "next-page"},
    ))) as client:
        provider = ScrapeCreatorsProvider("test", client=client)
        batch = await provider.get_comment_batch(_post(), known_comment_ids={"known"}, max_pages=1)
    assert batch.next_cursor == "next-page"
    assert batch.coverage_status == "PARTIAL"


async def test_same_public_discovery_response_includes_reels_photos_and_carousels():
    requests = []

    def handler(request):
        requests.append(request.url.path)
        return httpx.Response(200, json={"items": [
            {"id": "reel", "code": "reel", "product_type": "clips", "comment_count": 1},
            {"id": "photo", "code": "photo", "product_type": "feed", "comment_count": 1},
            {"id": "carousel", "code": "carousel", "media_type": 8, "comment_count": 1},
        ]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        posts = await ScrapeCreatorsProvider("test", client=client).get_reels("aiko.uz")
    assert requests == ["/v2/instagram/user/posts"]
    assert [post.platform_post_id for post in posts] == ["reel", "photo", "carousel"]
    assert [post.post_type for post in posts] == ["REEL", "POST", "POST"]
    assert [post.url for post in posts] == [
        "https://www.instagram.com/reel/reel/", "https://www.instagram.com/p/photo/",
        "https://www.instagram.com/p/carousel/",
    ]


async def test_budgeted_failed_second_page_returns_first_page_and_retry_cursor(session_factory):
    await seed_scrapecreators_instagram_policy(session_factory)
    cursors = []

    def handler(request):
        cursor = request.url.params.get("cursor")
        cursors.append(cursor)
        if cursor:
            raise httpx.ReadTimeout("second page timed out")
        return httpx.Response(200, json={
            "comments": [_comment_payload("first")], "cursor": "second-page",
            "credits_charged": 1,
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        inner = ScrapeCreatorsProvider("test", client=client, max_attempts=1)
        budget = ScanBudget(default_limit=5)
        provider = BudgetedInstagramProvider(inner, ExternalUsageService(session_factory),
                                            enabled=True, daily_limit=100, scan_budget=budget)
        batch = await provider.get_comment_batch(_post(), max_pages=2)
    assert cursors == [None, "second-page"]
    assert [item.platform_comment_id for item in batch.comments] == ["first"]
    assert batch.pages_fetched == 1
    assert batch.next_cursor == "second-page"
    assert batch.coverage_status == "PARTIAL"
    assert batch.fetch_error == "ProviderCallUncertainError"
    assert budget.used == 2
    async with session_factory() as session:
        statuses = list(await session.scalars(select(ExternalBudgetReservation.status)
                                             .order_by(ExternalBudgetReservation.id)))
    assert statuses == [ReservationStatus.FINALIZED, ReservationStatus.UNCERTAIN]


@pytest.mark.parametrize("charged", [0, 2])
async def test_confirmed_failed_later_page_preserves_results_without_uncertain_charge(session_factory, charged):
    from app.db.models import CostEvent

    await seed_scrapecreators_instagram_policy(session_factory)
    cursors = []

    def handler(request):
        cursor = request.url.params.get("cursor")
        cursors.append(cursor)
        if cursor:
            return httpx.Response(500, json={"error": "upstream", "credits_charged": charged})
        return httpx.Response(200, json={
            "comments": [_comment_payload("first")], "cursor": "second-page",
            "credits_charged": 1,
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = BudgetedInstagramProvider(
            ScrapeCreatorsProvider("test-local", client=client, max_attempts=3),
            ExternalUsageService(session_factory), enabled=True, daily_limit=100,
            scan_budget=ScanBudget(default_limit=5),
        )
        batch = await provider.get_comment_batch(_post(), max_pages=3)
    assert cursors == [None, "second-page"]
    assert [item.platform_comment_id for item in batch.comments] == ["first"]
    assert batch.next_cursor == "second-page" and batch.pages_fetched == 1
    assert batch.coverage_status == "PARTIAL" and not batch.cursor_exhausted
    assert batch.fetch_error == "ProviderCallFailedError"
    assert provider.scan_budget.used == 1 + charged
    async with session_factory() as session:
        reservations = list(await session.scalars(select(ExternalBudgetReservation).order_by(ExternalBudgetReservation.id)))
        costs = list(await session.scalars(select(CostEvent).order_by(CostEvent.id)))
    assert [row.status for row in reservations] == [ReservationStatus.FINALIZED] * 2
    assert [row.units for row in costs] == [1, charged]
    assert {row.unit_source for row in costs} == {"PROVIDER_CONFIRMED"}


async def test_monitor_commits_paid_page_after_later_page_failure_and_resumes(session_factory):
    await seed_scrapecreators_instagram_policy(session_factory)
    failed_once = False

    def handler(request):
        nonlocal failed_once
        cursor = request.url.params.get("cursor")
        if cursor and not failed_once:
            failed_once = True
            raise httpx.ReadTimeout("second page timed out")
        return httpx.Response(200, json={
            "comments": [_comment_payload("second" if cursor else "first")],
            "cursor": None if cursor else "second-page", "credits_charged": 1,
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        inner = ScrapeCreatorsProvider("test", client=client, max_attempts=1)
        provider = BudgetedInstagramProvider(inner, ExternalUsageService(session_factory),
                                            enabled=True, daily_limit=100,
                                            scan_budget=ScanBudget(default_limit=5))
        monitor = _monitor(session_factory, provider)
        post = _post()
        check = await monitor._prepare_post(post)
        stats = CycleStats()
        await monitor._process_prepared_reel(post, check, stats)
        await monitor._complete_baseline(post.competitor)
        assert stats.comments_created == 1
        assert stats.errors == 1
        resume = await monitor._prepare_post(post)
        assert resume.comment_cursor == "second-page"
        from app.providers.base import ProviderUsageBlockedError

        with pytest.raises(ProviderUsageBlockedError):
            await monitor._process_prepared_reel(post, resume, CycleStats())
        async with session_factory() as session:
            uncertain = await session.scalar(select(ExternalBudgetReservation.id).where(
                ExternalBudgetReservation.status == ReservationStatus.UNCERTAIN,
            ))
        # The simulated failed delivery was not charged; manual reconciliation
        # must precede retrying its durable cursor.
        assert await provider.usage.reconcile_uncertain_reservation(uncertain, spent=False)
        await monitor._process_prepared_reel(post, resume, CycleStats())
    async with session_factory() as session:
        assert await session.scalar(select(func.count(Comment.id))) == 2
        assert await session.scalar(select(func.count(Lead.id))) == 2


async def test_first_page_failure_still_raises_and_does_not_claim_empty_success(session_factory):
    await seed_scrapecreators_instagram_policy(session_factory)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(
        500, json={"error": "unavailable"},
    ))) as client:
        provider = BudgetedInstagramProvider(
            ScrapeCreatorsProvider("test", client=client, max_attempts=1),
            ExternalUsageService(session_factory), enabled=True, daily_limit=100,
            scan_budget=ScanBudget(default_limit=5),
        )
        with pytest.raises(ProviderCallUncertainError):
            await provider.get_comment_batch(_post(), max_pages=2)


async def test_existing_comment_recovers_lead_after_failure_between_commits(session_factory):
    provider = MockInstagramProvider()
    monitor = _monitor(session_factory, provider)
    original_ensure = monitor.lead_service.ensure_analyzing
    failures = 0

    async def fail_once(signal):
        nonlocal failures
        if failures == 0:
            failures += 1
            raise RuntimeError("simulated interruption after Comment commit")
        return await original_ensure(signal)

    monitor.lead_service.ensure_analyzing = fail_once
    first = await monitor.run_cycle()
    second = await monitor.run_cycle()
    repeated = await monitor.run_cycle()
    assert first.errors == 1
    assert second.comments_created == 0
    assert second.leads_created == 1
    assert repeated.leads_created == 0
    async with session_factory() as session:
        assert await session.scalar(select(func.count(Comment.id))) == 1
        assert await session.scalar(select(func.count(Lead.id))) == 1


@pytest.mark.parametrize("existing", [False, True])
async def test_partial_failure_preserves_cursor_without_completing_source_baseline(
    session_factory, existing,
):
    class PartialFailureProvider(MockInstagramProvider):
        async def get_comment_batch(self, post, *, cursor=None, **kwargs):
            first_comment = self._comments[0]
            if cursor is None:
                return CommentFetchResult(
                    comments=[first_comment], provider=self.name, pages_fetched=1,
                    coverage_status="PARTIAL", cursor_exhausted=False,
                    next_cursor="failed-page", fetch_error="ProviderCallUncertainError",
                )
            assert cursor == "failed-page"
            return CommentFetchResult(
                comments=[first_comment.model_copy(update={
                    "platform_comment_id": "second-comment",
                })], provider=self.name, pages_fetched=1,
                coverage_status="FULL", cursor_exhausted=True,
            )

    provider = PartialFailureProvider()
    provider._post = provider._post.model_copy(update={"comments_count": 2})
    first_monitor = _monitor(session_factory, provider, existing=existing,
                             baseline_max_comment_pages=2)
    first = await first_monitor.run_cycle()
    assert first.errors == 1
    async with session_factory() as session:
        competitor = await session.scalar(select(Competitor))
        post = await session.scalar(select(Post))
        assert competitor.baseline_completed_at is None
        assert competitor.scan_error_count == 1
        assert post.comment_backfill_cursor == "failed-page"
        assert await session.scalar(select(func.count(Comment.id))) == 1

    # A new worker has no in-memory knowledge of the interrupted scan.
    restarted = _monitor(session_factory, provider, existing=existing,
                         baseline_max_comment_pages=2)
    second = await restarted.run_cycle()
    assert second.errors == 0
    async with session_factory() as session:
        competitor = await session.scalar(select(Competitor))
        post = await session.scalar(select(Post))
        assert competitor.baseline_completed_at is not None
        assert competitor.scan_error_count == 0
        assert post.comment_backfill_cursor is None
        assert await session.scalar(select(func.count(Comment.id))) == 2
        assert await session.scalar(select(func.count(Lead.id))) == (2 if existing else 0)


async def test_unwrapped_provider_retains_prior_page_when_later_request_fails():
    def handler(request):
        if request.url.params.get("cursor"):
            raise httpx.ReadTimeout("interrupted next page")
        return httpx.Response(200, json={
            "comments": [_comment_payload("first")], "cursor": "retry-page",
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = ScrapeCreatorsProvider("test", client=client, max_attempts=1)
        batch = await provider.get_comment_batch(_post(), max_pages=2)
    assert [item.platform_comment_id for item in batch.comments] == ["first"]
    assert batch.next_cursor == "retry-page"
    assert batch.fetch_error == "ProviderError"
    assert not batch.cursor_exhausted


async def test_remaining_cursor_keeps_partial_coverage_despite_stored_count_matching_metadata(
    session_factory,
):
    class RemainingPageProvider(MockInstagramProvider):
        async def get_comment_batch(self, post, **kwargs):
            return CommentFetchResult(
                comments=list(self._comments), provider=self.name, pages_fetched=1,
                coverage_status="PARTIAL", cursor_exhausted=False, next_cursor="more-comments",
            )

    provider = RemainingPageProvider()
    monitor = _monitor(session_factory, provider)
    await monitor.run_cycle()
    async with session_factory() as session:
        post = await session.scalar(select(Post))
        assert post.comments_fetched_count == post.comments_count == 1
        assert post.coverage_status == CoverageStatus.PARTIAL
        assert post.comment_backfill_cursor == "more-comments"


async def test_malformed_later_page_preserves_previous_page_and_failed_cursor():
    def handler(request):
        if request.url.params.get("cursor"):
            return httpx.Response(200, json={"error": "malformed response"})
        return httpx.Response(200, json={
            "comments": [_comment_payload("first")], "cursor": "failed-page",
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        batch = await ScrapeCreatorsProvider("test", client=client).get_comment_batch(
            _post(), max_pages=2,
        )
    assert [item.platform_comment_id for item in batch.comments] == ["first"]
    assert batch.next_cursor == "failed-page"
    assert batch.fetch_error == "ProviderResponseError"
    assert batch.coverage_status == "PARTIAL"
    assert not batch.cursor_exhausted


@pytest.mark.parametrize("bad_record", [
    {"id": "bad", "text": "narxi?", "user": None},
    {"id": "bad", "text": "narxi?", "user": {"username": "buyer"},
     "created_at": "invalid-provider-time"},
    "not-a-comment-object",
])
async def test_malformed_record_preserves_valid_comments_on_both_sides(bad_record):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(
        200, json={"comments": [_comment_payload("before"), bad_record,
                                _comment_payload("after")], "cursor": "later-page"},
    ))) as client:
        batch = await ScrapeCreatorsProvider("test", client=client).get_comment_batch(
            _post(), max_pages=3,
        )
    assert [item.platform_comment_id for item in batch.comments] == ["before", "after"]
    # None means retry the first page, not falsely advance past its invalid item.
    assert batch.next_cursor is None
    assert batch.pages_fetched == 1
    assert batch.fetch_error == "ProviderResponseError"
    assert batch.coverage_status == "PARTIAL"
    assert not batch.cursor_exhausted


@pytest.mark.parametrize("payload", [
    {"error": "no comments array"},
    {"comments": [{"id": "bad", "text": "narxi?", "user": None}]},
])
async def test_malformed_first_page_without_valid_records_still_raises(payload):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(
        200, json=payload,
    ))) as client:
        with pytest.raises(ProviderResponseError):
            await ScrapeCreatorsProvider("test", client=client).get_comment_batch(_post())


async def test_budgeted_partial_decode_returns_without_paying_for_immediate_retry(session_factory):
    await seed_scrapecreators_instagram_policy(session_factory)
    cursors = []

    def handler(request):
        cursor = request.url.params.get("cursor")
        cursors.append(cursor)
        items = [_comment_payload("first")]
        if cursor:
            items = [_comment_payload("second"), {"id": "bad", "user": None}]
        return httpx.Response(200, json={
            "comments": items, "cursor": "next-page", "credits_charged": 1,
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        budget = ScanBudget(default_limit=5)
        provider = BudgetedInstagramProvider(
            ScrapeCreatorsProvider("test", client=client), ExternalUsageService(session_factory),
            enabled=True, daily_limit=100, scan_budget=budget,
        )
        batch = await provider.get_comment_batch(_post(), max_pages=3)
    assert cursors == [None, "next-page"]
    assert [item.platform_comment_id for item in batch.comments] == ["first", "second"]
    assert batch.fetch_error == "ProviderResponseError"
    assert batch.next_cursor == "next-page"
    assert batch.pages_fetched == budget.used == 2
    async with session_factory() as session:
        rows = list(await session.scalars(select(ExternalBudgetReservation)
                                         .order_by(ExternalBudgetReservation.id)))
        assert all(row.status == ReservationStatus.FINALIZED for row in rows)
        assert rows[-1].details_json["fetch_error"] == "ProviderResponseError"


@pytest.mark.parametrize("existing", [False, True])
async def test_malformed_head_page_cannot_acknowledge_full_coverage_and_recovers_manually(
    session_factory, existing,
):
    await seed_scrapecreators_instagram_policy(session_factory)
    repaired = False
    requests = []

    def handler(request):
        requests.append(request.url.path)
        if request.url.path.endswith("/user/posts"):
            return httpx.Response(200, json={"items": [{
                "id": "capture-post", "code": "capture", "comment_count": 2,
            }], "credits_charged": 1})
        items = [_comment_payload("before"), _comment_payload("after")]
        if not repaired:
            items.insert(1, {"id": "invalid-record", "text": "narxi?", "user": None})
        return httpx.Response(200, json={"comments": items, "credits_charged": 1})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = BudgetedInstagramProvider(
            ScrapeCreatorsProvider("test", client=client), ExternalUsageService(session_factory),
            enabled=True, daily_limit=100, scan_budget=ScanBudget(default_limit=5),
        )
        monitor = _monitor(session_factory, provider, existing=existing,
                           baseline_max_comment_pages=3)
        failed = await monitor.run_cycle()
        assert failed.errors == 1
        assert failed.comments_created == 2
        assert len(requests) == 2  # One discovery, one comment page, no automatic retry.
        async with session_factory() as session:
            post = await session.scalar(select(Post))
            competitor = await session.scalar(select(Competitor))
            assert post.comments_fetched_count == post.comments_count == 2
            assert post.coverage_status == CoverageStatus.PARTIAL
            assert post.comments_checked_at is None
            assert post.last_synced_remote_count is None
            assert post.comment_backfill_completed_at is None
            assert competitor.baseline_completed_at is None
            assert competitor.scan_error_count == 1
        repaired = True
        succeeded = await monitor.run_cycle()
        assert succeeded.errors == 0
        assert succeeded.comments_created == succeeded.leads_created == 0
        async with session_factory() as session:
            post = await session.scalar(select(Post))
            competitor = await session.scalar(select(Competitor))
            assert post.coverage_status == CoverageStatus.FULL
            assert post.last_synced_remote_count == 2
            assert post.comments_checked_at is not None
            assert competitor.baseline_completed_at is not None
            assert competitor.scan_error_count == 0
            assert await session.scalar(select(func.count(Comment.id))) == 2
            assert await session.scalar(select(func.count(Lead.id))) == (2 if existing else 0)


async def test_partial_decode_preserves_previous_success_metadata_for_due_head_refresh(
    session_factory,
):
    class DamagedRefreshProvider(MockInstagramProvider):
        damaged = False

        async def get_comment_batch(self, post, **kwargs):
            batch = await super().get_comment_batch(post, **kwargs)
            if self.damaged:
                batch = batch.model_copy(update={
                    "fetch_error": "ProviderResponseError", "coverage_status": "PARTIAL",
                    "cursor_exhausted": False,
                })
            return batch

    provider = DamagedRefreshProvider()
    monitor = _monitor(session_factory, provider, force_refresh_seconds=3600)
    await monitor.run_cycle()
    old_checked = datetime.now(UTC) - timedelta(hours=2)
    async with session_factory() as session:
        await session.execute(update(Post).values(comments_checked_at=old_checked))
        await session.commit()
    provider.damaged = True
    assert (await monitor.run_cycle()).errors == 1
    async with session_factory() as session:
        post = await session.scalar(select(Post))
        assert post.comments_checked_at.replace(tzinfo=UTC) == old_checked
        assert post.last_synced_remote_count == 1
        assert post.coverage_status == CoverageStatus.PARTIAL
    assert (await monitor._prepare_post(provider._post)).should_fetch_comments


@pytest.mark.parametrize("budgeted", [False, True])
async def test_restricted_later_page_propagates_instead_of_returning_partial_public_batch(
    session_factory, budgeted,
):
    await seed_scrapecreators_instagram_policy(session_factory)

    def handler(request):
        items = [_comment_payload("public")]
        if request.url.params.get("cursor"):
            items.append({"id": "hidden", "is_hidden": True, "user": {"username": "buyer"}})
        return httpx.Response(200, json={
            "comments": items, "cursor": "next-page", "credits_charged": 1,
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = ScrapeCreatorsProvider("test", client=client)
        if budgeted:
            provider = BudgetedInstagramProvider(
                provider, ExternalUsageService(session_factory), enabled=True, daily_limit=100,
                scan_budget=ScanBudget(default_limit=5),
            )
        with pytest.raises(ProviderPrivacyError):
            await provider.get_comment_batch(_post(), max_pages=3)
