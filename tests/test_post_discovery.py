from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import func, select

from app.db.models import Comment, CoverageStatus, Lead, Post, PostDiscoveryState
from app.db.repositories import CompetitorRepository
from app.providers.base import ProviderError, ProviderPrivacyError, ProviderResponseError
from app.providers.budgeted import BudgetedInstagramProvider, ScanBudget, ScanBudgetExceededError
from app.providers.fallback import FallbackInstagramProvider
from app.providers.mock import MockInstagramProvider
from app.providers.scrapecreators import ScrapeCreatorsProvider
from app.schemas.instagram import PostFetchResult
from app.services.contact_service import ContactService
from app.services.instagram_monitor import InstagramMonitor
from app.services.lead_service import LeadService
from app.services.post_discovery_service import PostDiscoveryService
from app.services.usage_service import ExternalUsageService
from app.web.queries import WebQueryService
from tests.conftest import seed_scrapecreators_instagram_policy
from tests.test_lead_service import StaticAnalyzer
from tests.test_monitor import RecordingNotifier


def post_item(identifier="p1", *, comments=1, age_days=0, product_type="clips"):
    return {
        "id": identifier, "code": identifier, "product_type": product_type,
        "taken_at": int((datetime.now(UTC) - timedelta(days=age_days)).timestamp()),
        "comment_count": comments, "caption": {"text": "Стол и стулья"},
    }


@pytest.mark.parametrize(("fields", "coverage", "error", "next_cursor", "exhausted"), [
    ({"more_available": True, "next_max_id": "B"}, "PARTIAL", None, "B", False),
    ({"more_available": False}, "FULL", None, None, True),
    ({"more_available": False, "next_max_id": ""}, "FULL", None, None, True),
    ({"next_max_id": "B"}, "PARTIAL", None, "B", False),
    ({}, "UNKNOWN", None, None, False),
    ({"more_available": True}, "PARTIAL", "MissingPostCursor", "A", False),
    ({"more_available": "false"}, "PARTIAL", "InvalidPostPagination", "A", False),
    ({"next_max_id": ["secret"]}, "PARTIAL", "InvalidPostCursor", "A", False),
    ({"next_max_id": 123}, "PARTIAL", "InvalidPostCursor", "A", False),
    ({"next_max_id": "x" * 4097}, "PARTIAL", "InvalidPostCursor", "A", False),
    ({"more_available": False, "next_max_id": "B"}, "PARTIAL", "ConflictingPostPagination", "A", False),
    ({"more_available": True, "next_max_id": "A"}, "PARTIAL", "RepeatedPostCursor", "A", False),
])
async def test_publication_page_contract(fields, coverage, error, next_cursor, exhausted):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"items": [post_item()], **fields})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        page = await ScrapeCreatorsProvider("test-only", client=client).get_post_page("aiko.uz", cursor="A")
    assert len(requests) == 1
    assert requests[0].url.params["next_max_id"] == "A"
    assert requests[0].url.params["handle"] == "aiko.uz"
    assert page.coverage_status == coverage
    assert page.fetch_error == error
    assert page.next_cursor == next_cursor
    assert page.cursor_exhausted is exhausted
    assert len(page.posts) == 1


@pytest.mark.parametrize("bad", [None, "broken", {}, {"id": "missing-code"}, post_item(comments=-1)])
async def test_malformed_sibling_does_not_skip_page(bad):
    payload = {"items": [post_item(), bad, post_item()], "more_available": True, "next_max_id": "B"}
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))) as client:
        page = await ScrapeCreatorsProvider("test-only", client=client).get_post_page("aiko.uz", cursor="A")
    assert [post.platform_post_id for post in page.posts] == ["p1"]
    assert page.next_cursor == "A" and page.fetch_error == "MalformedPost"


async def test_photos_carousels_and_public_data_only():
    item = post_item(product_type="carousel_container")
    item.update({"email": "not-retained@example.test", "phone_number": "not-retained"})
    payload = {"items": [item, post_item("reel")], "more_available": False}
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))) as client:
        page = await ScrapeCreatorsProvider("test-only", client=client).get_post_page("aiko.uz")
    assert [post.post_type for post in page.posts] == ["POST", "REEL"]
    assert all("email" not in post.raw_data and "phone_number" not in post.raw_data for post in page.posts)


async def test_private_source_rejected_even_with_valid_siblings():
    payload = {"items": [post_item(), {**post_item("private"), "user": {"is_private": True}}], "more_available": False}
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))) as client:
        with pytest.raises(ProviderPrivacyError):
            await ScrapeCreatorsProvider("test-only", client=client).get_post_page("aiko.uz")


async def test_one_reservation_cannot_trigger_http_retries():
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(500)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(ProviderError):
            await ScrapeCreatorsProvider("test-only", max_attempts=3, client=client).get_post_page("aiko.uz")
    assert len(requests) == 1


async def test_legacy_adapter_reports_unknown_and_rejects_cursor():
    provider = MockInstagramProvider()
    page = await provider.get_post_page("aiko.uz")
    assert page.coverage_status == "UNKNOWN" and not page.cursor_exhausted
    with pytest.raises(ProviderResponseError):
        await provider.get_post_page("aiko.uz", cursor="foreign")


async def test_fallback_never_receives_primary_publication_cursor():
    class Failing(MockInstagramProvider):
        name = "primary"

        async def get_post_page(self, handle, *, cursor=None):
            raise ProviderError("temporary")

    provider = FallbackInstagramProvider(Failing(), MockInstagramProvider())
    with pytest.raises(ProviderError):
        await provider.get_post_page("aiko.uz", cursor="primary-only")
    page = await provider.get_post_page("aiko.uz")
    assert page.provider == "mock" and page.coverage_status == "UNKNOWN"


@pytest.mark.parametrize("limit", [0, 1, 2, 3, 5])
async def test_each_publication_page_has_its_own_budget_reservation(session_factory, limit):
    await seed_scrapecreators_instagram_policy(session_factory)
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"items": [], "more_available": False, "credits_charged": 1})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = BudgetedInstagramProvider(ScrapeCreatorsProvider("test-only", client=client),
            ExternalUsageService(session_factory), enabled=True, daily_limit=100, scan_budget=ScanBudget(limit))
        provider.begin_cycle()
        for _ in range(limit):
            await provider.get_post_page("aiko.uz")
        with pytest.raises(ScanBudgetExceededError):
            await provider.get_post_page("aiko.uz", cursor="A")
        assert provider.scan_budget_status()["used"] == limit
    assert len(requests) == limit
    assert await ExternalUsageService(session_factory).used_today("instagram") == limit


async def record(session_factory, *, cursor=None, next_cursor="A", exhausted=False, error=None, provider="scrapecreators"):
    async with session_factory() as session:
        competitor = await CompetitorRepository(session).get_or_create("aiko.uz")
        state = await PostDiscoveryService(session).record_page(competitor.id,
            PostFetchResult(provider=provider, next_cursor=next_cursor, cursor_exhausted=exhausted,
                            coverage_status="FULL" if exhausted else "PARTIAL", fetch_error=error),
            requested_cursor=cursor)
        await session.commit()
        return state


async def test_head_refresh_restart_and_replayed_page_preserve_continuation(file_session_factory):
    await record(file_session_factory)
    await record(file_session_factory, cursor="A", next_cursor="B")
    state = await record(file_session_factory, next_cursor="A")
    assert state.next_cursor == "B" and state.visited_cursors == ["A"]
    state = await record(file_session_factory, cursor="A", next_cursor="wrong")
    assert state.next_cursor == "B"
    state = await record(file_session_factory, cursor="B", next_cursor=None, exhausted=True)
    assert state.coverage_status == CoverageStatus.FULL and state.completed_at is not None
    assert state.next_cursor is None


async def test_failed_page_does_not_advance_cursor(session_factory):
    await record(session_factory)
    state = await record(session_factory, cursor="A", next_cursor="B", error="MalformedPost")
    assert state.next_cursor == "A" and state.completed_at is None
    assert state.stop_reason == "MalformedPost"
    state = await record(session_factory, cursor="A", next_cursor="B")
    assert state.next_cursor == "B"


async def test_failure_receipts_are_idempotent_and_cannot_rewind_newer_pages(session_factory):
    state = await record(session_factory)
    failed_at = datetime.now(UTC) + timedelta(seconds=1)
    async with session_factory() as session:
        service = PostDiscoveryService(session)
        changed = await service.record_failure(state.competitor_id, state.provider,
            requested_cursor="A", error_type="ProviderCallFailedError", failed_at=failed_at)
        assert changed.next_cursor == "A" and changed.visited_cursors == []
        assert changed.coverage_status == CoverageStatus.PARTIAL and changed.completed_at is None
        await session.commit()
        assert await service.record_failure(state.competitor_id, state.provider,
            requested_cursor="A", error_type="duplicate", failed_at=failed_at) is None
        assert await service.record_failure(state.competitor_id, state.provider,
            requested_cursor="A", error_type="stale", failed_at=failed_at-timedelta(seconds=1)) is None
    await record(session_factory, cursor="A", next_cursor="B")
    async with session_factory() as session:
        assert await PostDiscoveryService(session).record_failure(state.competitor_id, state.provider,
            requested_cursor="A", error_type="delayed", failed_at=failed_at+timedelta(seconds=5)) is None
        saved = await session.get(PostDiscoveryState, state.id)
        assert saved.next_cursor == "B" and saved.visited_cursors == ["A"]


@pytest.mark.parametrize("failure", ["http", "malformed"])
async def test_failed_historical_page_does_not_starve_other_companies(session_factory, failure):
    await seed_scrapecreators_instagram_policy(session_factory)
    continuations = []

    def respond(request):
        handle = request.url.params["handle"]
        cursor = request.url.params.get("next_max_id")
        if cursor and handle == "aiko.uz":
            continuations.append(handle)
            return httpx.Response(500 if failure == "http" else 200,
                json={"items": [{}], "credits_charged": 0})
        if cursor:
            continuations.append(handle)
        return httpx.Response(200, json={"items": [], "credits_charged": 1,
            "more_available": not bool(cursor), "next_max_id": None if cursor else handle+"-A"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = BudgetedInstagramProvider(ScrapeCreatorsProvider("test-only", client=client),
            ExternalUsageService(session_factory), enabled=True, daily_limit=100, scan_budget=ScanBudget(6))
        instance = monitor(session_factory, provider)
        instance.competitors = ["aiko.uz", "beta"]
        first = await instance.run_cycle()
        assert first.errors == 1
        second = await instance.run_cycle()
        assert second.errors == 0
    assert continuations == ["aiko.uz", "beta"]
    async with session_factory() as session:
        states = {row.provider+str(row.competitor_id): row for row in await session.scalars(select(PostDiscoveryState))}
        assert len(states) == 2
        pending = [row for row in states.values() if row.next_cursor]
        assert len(pending) == 1 and pending[0].next_cursor == "aiko.uz-A"
        assert pending[0].coverage_status == CoverageStatus.PARTIAL
        assert len([row for row in states.values() if row.completed_at is not None]) == 1


async def test_loop_across_separate_cycles_is_blocked(session_factory):
    await record(session_factory)
    await record(session_factory, cursor="A", next_cursor="B")
    state = await record(session_factory, cursor="B", next_cursor="A")
    assert state.stop_reason == "RepeatedPostCursor" and state.next_cursor == "B"
    state = await record(session_factory, next_cursor="A")
    assert state.stop_reason == "RepeatedPostCursor" and state.coverage_status == CoverageStatus.PARTIAL


async def test_provider_positions_are_isolated(session_factory):
    await record(session_factory)
    await record(session_factory, provider="other", next_cursor="other-A")
    async with session_factory() as session:
        states = list(await session.scalars(select(PostDiscoveryState).order_by(PostDiscoveryState.id)))
        assert [state.next_cursor for state in states] == ["A", "other-A"]


async def test_exhausted_traversal_reopens_after_refresh_interval(session_factory):
    state = await record(session_factory, next_cursor=None, exhausted=True)
    async with session_factory() as session:
        stored = await session.get(PostDiscoveryState, state.id)
        stored.completed_at = datetime.now(UTC) - timedelta(days=1)
        await session.commit()
    state = await record(session_factory)
    assert state.next_cursor == "A" and state.completed_at is None


def monitor(session_factory, provider):
    return InstagramMonitor(session_factory=session_factory, provider=provider,
        contact_service=ContactService(session_factory),
        lead_service=LeadService(session_factory, StaticAnalyzer(), hot_threshold=70),
        notifier=RecordingNotifier(), competitors=["aiko.uz"], process_existing_comments=True)


def staged_transport(requests):
    def respond(request):
        requests.append(request)
        if request.url.path.endswith("user/posts"):
            cursor = request.url.params.get("next_max_id")
            items = [post_item("p1"), post_item("p2")] if cursor is None else [post_item("old", age_days=365)] if cursor == "A" else []
            return httpx.Response(200, json={"items": items, "more_available": cursor != "B",
                "next_max_id": "A" if cursor is None else "B" if cursor == "A" else None,
                "credits_charged": 1})
        identifier = request.url.params["url"].rstrip("/").split("/")[-1]
        return httpx.Response(200, json={"comments": [{"id": "c-"+identifier, "text": "narxi?",
            "created_at": int(datetime.now(UTC).timestamp()), "user": {"id": "u-"+identifier, "username": "user_"+identifier}}],
            "has_more": False, "credits_charged": 1})
    return httpx.MockTransport(respond)


async def test_budget_stop_does_not_strand_previous_page_comments_after_restart(file_session_factory):
    await seed_scrapecreators_instagram_policy(file_session_factory)
    requests = []
    async with httpx.AsyncClient(transport=staged_transport(requests)) as client:
        for _ in range(4):
            # New provider/monitor each time; only SQLite survives the restart.
            provider = BudgetedInstagramProvider(ScrapeCreatorsProvider("test-only", client=client),
                ExternalUsageService(file_session_factory), enabled=True, daily_limit=100, scan_budget=ScanBudget(2))
            stats = await monitor(file_session_factory, provider).run_cycle()
            assert stats.errors == 0
            assert provider.scan_budget_status()["used"] <= 2
        assert stats.saved_posts_resumed == 1
    async with file_session_factory() as session:
        assert await session.scalar(select(func.count(Post.id))) == 3
        assert await session.scalar(select(func.count(Comment.id))) == 3
        assert await session.scalar(select(func.count(Lead.id))) == 3
        state = await session.scalar(select(PostDiscoveryState))
        assert state.next_cursor == "B"
        old = await session.scalar(select(Post).where(Post.platform_post_id == "old"))
        assert old.comments_checked_at is not None
        rows = await WebQueryService(file_session_factory, 70).competitors()
        assert rows[0]["post_discovery"][0].next_cursor == "B"
        assert rows[0]["pending_comment_posts"] == 0


@pytest.mark.parametrize("limit", [0, 1, 2, 3, 5])
async def test_manual_cycle_never_exceeds_selected_cap(session_factory, limit):
    await seed_scrapecreators_instagram_policy(session_factory)
    requests = []
    async with httpx.AsyncClient(transport=staged_transport(requests)) as client:
        provider = BudgetedInstagramProvider(ScrapeCreatorsProvider("test-only", client=client),
            ExternalUsageService(session_factory), enabled=True, daily_limit=100, scan_budget=ScanBudget(limit))
        stats = await monitor(session_factory, provider).run_cycle()
        assert stats.errors == 0
        assert len(requests) <= limit
        assert provider.scan_budget_status()["used"] <= limit
        assert stats.post_pages_fetched <= 2


async def test_storage_failure_rolls_back_publications_and_cursor(session_factory, monkeypatch):
    await seed_scrapecreators_instagram_policy(session_factory)
    requests = []
    async with httpx.AsyncClient(transport=staged_transport(requests)) as client:
        raw_provider = ScrapeCreatorsProvider("test-only", client=client)
        instance = monitor(session_factory, raw_provider)
        prepare = instance._prepare_post_in_session

        async def failing(reel, session):
            if reel.platform_post_id == "p2":
                raise RuntimeError("database stage failed")
            return await prepare(reel, session)

        monkeypatch.setattr(instance, "_prepare_post_in_session", failing)
        stats = await instance.run_cycle()
    assert stats.errors == 1
    async with session_factory() as session:
        assert await session.scalar(select(func.count(Post.id))) == 0
        assert await session.scalar(select(func.count(PostDiscoveryState.id))) == 0
        assert await session.scalar(select(func.count(Comment.id))) == 0


async def test_small_budget_baseline_finishes_without_refetching_completed_posts(session_factory):
    await seed_scrapecreators_instagram_policy(session_factory)
    requests = []
    async with httpx.AsyncClient(transport=staged_transport(requests)) as client:
        provider = BudgetedInstagramProvider(ScrapeCreatorsProvider("test-only", client=client),
            ExternalUsageService(session_factory), enabled=True, daily_limit=100, scan_budget=ScanBudget(2))
        instance = monitor(session_factory, provider)
        instance.process_existing_comments = False
        first = await instance.run_cycle()
        second = await instance.run_cycle()
        assert first.comments_created == second.comments_created == 1
        assert first.leads_created == second.leads_created == 0
    urls = [request.url.params["url"] for request in requests if request.url.path.endswith("comments")]
    assert len(urls) == len(set(urls)) == 2
    async with session_factory() as session:
        from app.db.models import Competitor
        competitor = await session.scalar(select(Competitor))
        assert competitor.baseline_completed_at is not None


async def test_blocked_loop_never_requests_another_paid_continuation(session_factory):
    await record(session_factory)
    await record(session_factory, cursor="A", next_cursor="B")
    await record(session_factory, cursor="B", next_cursor="A")
    class PagedMock(MockInstagramProvider):
        name = "scrapecreators"

    instance = monitor(session_factory, PagedMock())
    assert await instance._next_post_continuation({"aiko.uz"}) is None


async def test_unaccepted_cursor_is_rejected_before_budget_reservation(session_factory):
    provider = BudgetedInstagramProvider(MockInstagramProvider(), ExternalUsageService(session_factory),
        enabled=True, daily_limit=100, scan_budget=ScanBudget(5))
    with pytest.raises(ProviderResponseError):
        await provider.get_post_page("aiko.uz", cursor="foreign")
    assert provider.scan_budget_status()["used"] == 0


async def test_migration_has_no_schema_drift(migrated_database):
    from app.config import get_settings
    from app.services.deployment_readiness_service import inspect_offline_readiness
    state = await inspect_offline_readiness(get_settings())
    assert state.database_healthy and state.migration_at_head and state.migration_drift_free


async def test_provider_confirmed_overspend_stops_before_another_page(session_factory):
    await seed_scrapecreators_instagram_policy(session_factory)
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"items": [], "more_available": False, "credits_charged": 2})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = BudgetedInstagramProvider(ScrapeCreatorsProvider("test-only", client=client),
            ExternalUsageService(session_factory), enabled=True, daily_limit=100, scan_budget=ScanBudget(1))
        with pytest.raises(ScanBudgetExceededError):
            await provider.get_post_page("aiko.uz")
        with pytest.raises(ScanBudgetExceededError):
            await provider.get_post_page("aiko.uz", cursor="A")
    assert len(requests) == 1
    assert await ExternalUsageService(session_factory).used_today("instagram") == 2


@pytest.mark.parametrize("mode", ["partial", "full", "loop", "unknown"])
async def test_source_ui_renders_honest_coverage_without_exposing_cursor(session_factory, mode):
    from tests.test_web_security import _build_test_app, _dev_settings
    await record(session_factory, next_cursor="opaque-cursor-not-for-ui")
    async with session_factory() as session:
        state = await session.scalar(select(PostDiscoveryState))
        if mode == "full":
            state.next_cursor = None
            state.coverage_status = CoverageStatus.FULL
            state.completed_at = datetime.now(UTC)
        elif mode == "loop":
            state.stop_reason = "RepeatedPostCursor"
        elif mode == "unknown":
            state.next_cursor = None
            state.coverage_status = CoverageStatus.UNKNOWN
            state.stop_reason = "PaginationUnknown"
        await session.commit()
    app = _build_test_app(_dev_settings(), session_factory)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/competitors")
    assert response.status_code == 200
    assert "opaque-cursor-not-for-ui" not in response.text
    assert "Полнота публикаций и полнота комментариев проверяются отдельно." in response.text
    expected = {"partial": "Есть сохранённое продолжение", "full": "Все страницы получены",
                "loop": "Продолжение остановлено", "unknown": "Полнота пока не подтверждена"}
    assert expected[mode] in response.text
