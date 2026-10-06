"""Regressions reproduced by the October functional audit; no live API calls."""

import asyncio
import csv
import io
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import func, select, update

from app.db.models import AIRequest, AIRequestStatus, Comment, Contact, ContactEvent, Lead, Post
from app.providers.base import ProviderError
from app.providers.fallback import FallbackInstagramProvider
from app.providers.mock import MockInstagramProvider
from app.providers.scrapecreators import ScrapeCreatorsProvider
from app.schemas.instagram import InstagramPost
from app.services.ai_service import AIAnalysisError
from app.services.contact_service import ContactService
from app.services.crm_service import CRMService
from app.services.hot_outreach_service import HotOutreachService, StaticOutreachComposer
from app.services.instagram_monitor import CycleStats, InstagramMonitor
from app.services.lead_analysis_pipeline import LeadAnalysisPipeline
from app.services.lead_service import LeadService
from app.services.lead_workflow_service import LeadWorkflowError, LeadWorkflowService
from app.services.product_catalog_service import ProductCatalogService
from app.services.usage_service import ExternalBudgetExceeded, ExternalUsageService
from app.web.auth import TelegramWebAuth
from app.web.csv_export import safe_csv_row
from tests.test_contact_service import make_comment, make_post
from tests.test_hot_outreach import _make_hot_lead
from tests.test_lead_service import StaticAnalyzer
from tests.test_monitor import RecordingNotifier
from tests.test_provider_credit_budget import _add_policy
from tests.test_web_security import _build_test_app, _dev_settings, _secured_settings


def make_monitor(factory, provider, *, existing=True):
    return InstagramMonitor(
        session_factory=factory, provider=provider,
        contact_service=ContactService(factory),
        lead_service=LeadService(factory, StaticAnalyzer(), 70),
        notifier=RecordingNotifier(), competitors=["auditshop"],
        process_existing_comments=existing, incremental_max_comment_pages=1,
        baseline_max_comment_pages=1, auto_repair_partial_coverage=True,
        force_refresh_seconds=1,
    )


def paged_provider():
    cursors = []

    def respond(request):
        cursor = request.url.params.get("cursor")
        cursors.append(cursor)
        suffix = "older" if cursor else "newest"
        return httpx.Response(200, json={
            "comments": [{"id": f"page-{suffix}", "text": "narxi?",
                          "user": {"id": f"user-{suffix}", "username": suffix}}],
            "cursor": None if cursor else "page-2",
        })

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    return ScrapeCreatorsProvider("test-key", client=client), client, cursors


def paged_post():
    return InstagramPost(
        platform_post_id="paged", competitor="auditshop",
        url="https://www.instagram.com/reel/paged/", comments_count=2,
        published_at=datetime.now(UTC),
    )


@pytest.mark.parametrize("existing", [True, False])
async def test_comment_backfill_resumes_after_restart_and_preserves_baseline(session_factory, existing):
    provider, client, cursors = paged_provider()
    try:
        post = paged_post()
        monitor = make_monitor(session_factory, provider, existing=existing)
        first = await monitor._prepare_post(post)
        await monitor._process_prepared_reel(post, first, CycleStats())
        await monitor._complete_baseline(post.competitor)
        # A new monitor instance must recover its position from the database.
        restarted = make_monitor(session_factory, provider, existing=existing)
        second = await restarted._prepare_post(post)
        assert second.should_fetch_comments
        assert second.comment_cursor == "page-2"
        assert second.is_baseline is (not existing)
        await restarted._process_prepared_reel(post, second, CycleStats())
        assert cursors == [None, "page-2"]
        assert not (await restarted._prepare_post(post)).should_fetch_comments
        async with session_factory() as session:
            saved = await session.get(Post, first.post_id)
            assert saved.comments_fetched_count == 2
            assert saved.comment_backfill_cursor is None
            assert saved.comment_backfill_completed_at is not None
            assert await session.scalar(select(func.count(Comment.id))) == 2
            assert await session.scalar(select(func.count(Lead.id))) == (2 if existing else 0)
    finally:
        await client.aclose()


async def test_backfill_does_not_acknowledge_unfetched_new_head_comments(session_factory):
    provider, client, _ = paged_provider()
    try:
        post = paged_post()
        monitor = make_monitor(session_factory, provider)
        first = await monitor._prepare_post(post)
        await monitor._process_prepared_reel(post, first, CycleStats())
        await monitor._complete_baseline(post.competitor)
        newer_post = post.model_copy(update={"comments_count": 3})
        second = await monitor._prepare_post(newer_post)
        assert second.is_backfill
        await monitor._process_prepared_reel(newer_post, second, CycleStats())
        head = await monitor._prepare_post(newer_post)
        assert head.should_fetch_comments
        assert head.comment_cursor is None
        assert not head.is_backfill
    finally:
        await client.aclose()


async def test_legacy_partial_backfill_ignores_known_first_page(session_factory):
    provider, client, cursors = paged_provider()
    try:
        post = paged_post()
        monitor = make_monitor(session_factory, provider)
        first = await monitor._prepare_post(post)
        await monitor._process_prepared_reel(post, first, CycleStats())
        await monitor._complete_baseline(post.competitor)
        async with session_factory() as session:
            await session.execute(update(Post).values(
                comment_backfill_cursor=None,
                comments_checked_at=datetime.now(UTC) - timedelta(hours=2),
            ))
            await session.commit()
        repair = await monitor._prepare_post(post)
        assert repair.is_backfill
        await monitor._process_prepared_reel(post, repair, CycleStats())
        resume = await monitor._prepare_post(post)
        assert resume.comment_cursor == "page-2"
        await monitor._process_prepared_reel(post, resume, CycleStats())
        assert cursors == [None, None, "page-2"]
        async with session_factory() as session:
            assert await session.scalar(select(func.count(Comment.id))) == 2
    finally:
        await client.aclose()


async def test_cursor_is_discarded_when_provider_changes(session_factory):
    provider, client, _ = paged_provider()
    try:
        monitor = make_monitor(session_factory, provider)
        post = paged_post()
        check = await monitor._prepare_post(post)
        await monitor._process_prepared_reel(post, check, CycleStats())
        await monitor._complete_baseline(post.competitor)
        replacement = make_monitor(session_factory, MockInstagramProvider())
        check = await replacement._prepare_post(post)
        assert check.should_fetch_comments
        assert check.comment_cursor is None
    finally:
        await client.aclose()


async def test_cursor_never_crosses_fallback_provider():
    class BrokenPrimary(MockInstagramProvider):
        name = "primary"

        async def get_comment_batch(self, post, **kwargs):
            raise ProviderError("primary unavailable")

    class RecordingFallback(MockInstagramProvider):
        calls = 0

        async def get_comment_batch(self, post, **kwargs):
            self.calls += 1
            return await super().get_comment_batch(post, **kwargs)

    fallback = RecordingFallback()
    provider = FallbackInstagramProvider(BrokenPrimary(), fallback)
    with pytest.raises(ProviderError, match="primary unavailable"):
        await provider.get_comment_batch(paged_post(), cursor="opaque-primary-cursor")
    assert fallback.calls == 0


def outreach_service(factory, composer):
    return HotOutreachService(
        factory, hot_threshold=70, workflow=LeadWorkflowService(factory, 70),
        crm=CRMService(factory), catalog=ProductCatalogService(factory),
        usage=ExternalUsageService(factory), composer=composer, openai_daily_limit=10,
    )


class BlockingComposer:
    def __init__(self):
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.calls = 0

    async def compose(self, context):
        self.calls += 1
        self.entered.set()
        await asyncio.wait_for(self.release.wait(), 5)
        return "Подготовленное предложение"


@pytest.mark.parametrize("force", [True, False])
async def test_parallel_outreach_has_one_call_and_one_event(file_session_factory, force):
    factory = file_session_factory
    lead_id = await _make_hot_lead(factory)
    await LeadWorkflowService(factory, 70).assign_manager(lead_id, 1001)
    composer = BlockingComposer()
    first = outreach_service(factory, composer)
    second = outreach_service(factory, composer)
    task = asyncio.create_task(first.prepare(lead_id, 1001, force=force))
    try:
        await asyncio.wait_for(composer.entered.wait(), 5)
        with pytest.raises(LeadWorkflowError, match="уже готовится"):
            await second.prepare(lead_id, 1001, force=force)
    finally:
        composer.release.set()
        result = await task
    assert result["draft"]["message"] == "Подготовленное предложение"
    assert composer.calls == 1
    assert await first.usage.used_today("openai") == 1
    cached = await second.prepare(lead_id, 1001)
    assert cached["draft"] == result["draft"]
    assert composer.calls == 1
    async with factory() as session:
        lead = await session.get(Lead, lead_id)
        assert lead.outreach_claim_token is None
        events = (await session.scalars(select(ContactEvent))).all()
        assert sum((e.payload_json or {}).get("kind") == "hot_outreach_prepared" for e in events) == 1


async def test_outreach_recovers_expired_claim(session_factory):
    lead_id = await _make_hot_lead(session_factory)
    async with session_factory() as session:
        await session.execute(update(Lead).values(
            outreach_claim_token="crashed-worker",
            outreach_claim_expires_at=datetime.now(UTC) - timedelta(minutes=1),
        ))
        await session.commit()
    result = await outreach_service(session_factory, StaticOutreachComposer()).prepare(lead_id, 1001)
    assert result["draft"]["message"]


async def test_old_outreach_worker_cannot_overwrite_new_claim(file_session_factory):
    factory = file_session_factory
    lead_id = await _make_hot_lead(factory)
    composer = BlockingComposer()
    service = outreach_service(factory, composer)
    task = asyncio.create_task(service.prepare(lead_id, 1001))
    await asyncio.wait_for(composer.entered.wait(), 5)
    async with factory() as session:
        await session.execute(update(Lead).values(outreach_claim_token="new-owner"))
        await session.commit()
    composer.release.set()
    with pytest.raises(LeadWorkflowError, match="устарела"):
        await task
    async with factory() as session:
        lead = await session.get(Lead, lead_id)
        assert lead.outreach_claim_token == "new-owner"
        assert not (lead.analysis_details or {}).get("hot_outreach")


class FailedAnalyzer:
    def __init__(self):
        self.ids = []

    async def analyze(self, context):
        self.ids.append(context.lead_id)
        raise AIAnalysisError("temporary upstream error")


async def pending_leads(factory, analyzer):
    service = LeadService(factory, analyzer, 70)
    ids = []
    for suffix in ("first", "second"):
        signal = await ContactService(factory).persist_signal(make_post(), make_comment(suffix))
        ids.append((await service.ensure_analyzing(signal)).lead_id)
    return service, ids


@pytest.mark.parametrize("enabled", [True, False])
async def test_pending_failure_does_not_starve_next_lead(session_factory, enabled):
    analyzer = FailedAnalyzer()
    service, ids = await pending_leads(session_factory, analyzer)
    pipeline = LeadAnalysisPipeline(
        service, RecordingNotifier(), sync_mode=True,
        retry_pending_enabled=enabled, retry_pending_cooldown_seconds=3600,
    )
    for _ in range(3):
        await pipeline.enqueue_pending_batch(limit=1)
    assert analyzer.ids == ids
    async with session_factory() as session:
        await session.execute(update(Lead).values(
            ai_last_attempt_at=datetime.now(UTC) - timedelta(hours=2),
        ))
        await session.commit()
    count = await pipeline.enqueue_pending_batch(limit=1)
    assert count == (1 if enabled else 0)


async def test_pending_excludes_queued_rows_before_applying_limit(session_factory):
    analyzer = FailedAnalyzer()
    service, ids = await pending_leads(session_factory, analyzer)
    pipeline = LeadAnalysisPipeline(service, RecordingNotifier(), sync_mode=True)
    pipeline._queued_ids.add(ids[0])
    assert await pipeline.enqueue_pending_batch(limit=1) == 1
    assert analyzer.ids == [ids[1]]


async def test_pending_skips_permanent_failure_and_recovers_stale_job(session_factory):
    analyzer = FailedAnalyzer()
    service, ids = await pending_leads(session_factory, analyzer)
    async with session_factory() as session:
        session.add(AIRequest(
            lead_id=ids[0], context_fingerprint="permanent", model="test",
            status=AIRequestStatus.PERMANENT_FAILURE,
        ))
        await session.execute(update(Lead).values(
            ai_attempt_count=1, ai_last_attempt_at=datetime.now(UTC) - timedelta(hours=2),
        ))
        await session.commit()
    pipeline = LeadAnalysisPipeline(service, RecordingNotifier(), sync_mode=True)
    assert await pipeline.enqueue_pending_batch(limit=1) == 1
    assert analyzer.ids == [ids[1]]


@pytest.mark.parametrize("provider", ["scrapecreators", "brightdata"])
async def test_paid_instagram_requires_policy_even_without_daily_cap(session_factory, provider):
    with pytest.raises(ExternalBudgetExceeded, match=f"{provider}/instagram"):
        await ExternalUsageService(session_factory).reserve_budget(
            "instagram", "get_comments", 100, provider=provider, enforce_daily_limit=False,
        )


async def test_brightdata_monthly_cap_counts_previous_scans(session_factory):
    from app.db.models import ProviderBudgetPolicy

    await _add_policy(session_factory, hard=2)
    async with session_factory() as session:
        await session.execute(update(ProviderBudgetPolicy).values(provider="brightdata"))
        await session.commit()
    usage = ExternalUsageService(session_factory)
    for _ in range(2):
        reservation = await usage.reserve_budget(
            "instagram", "get_comments", 100, provider="brightdata", enforce_daily_limit=False,
        )
        await usage.finalize_reservation(reservation)
    with pytest.raises(ExternalBudgetExceeded, match="Месячный hard limit"):
        await usage.reserve_budget(
            "instagram", "get_comments", 100, provider="brightdata", enforce_daily_limit=False,
        )


async def test_outreach_uncertain_call_blocks_retry_until_reconciled(session_factory):
    class UncertainComposer:
        async def compose(self, context):
            raise TimeoutError("response lost")

    lead_id = await _make_hot_lead(session_factory)
    first = outreach_service(session_factory, UncertainComposer())
    with pytest.raises(LeadWorkflowError, match="Не удалось"):
        await first.prepare(lead_id, 1001)
    retry = outreach_service(session_factory, StaticOutreachComposer())
    with pytest.raises(LeadWorkflowError, match="сверить списание"):
        await retry.prepare(lead_id, 1001, force=True)
    assert await retry.usage.active_reservations_today("openai") == 1
    async with session_factory() as session:
        assert (await session.get(Lead, lead_id)).outreach_claim_token is None


@pytest.mark.parametrize("value", ["=1+1", "+1+1", "-1+1", "@SUM(A1)", " \t=1+1", "\ufeff=1+1", "\ttext", "\rtext"])
def test_csv_formula_text_is_escaped(value):
    assert safe_csv_row([value, 42, -12, "обычный текст", None]) == ["'" + value, 42, -12, "обычный текст", None]


async def test_csv_export_protects_external_fields(session_factory):
    lead_id = await _make_hot_lead(session_factory)
    async with session_factory() as session:
        lead = await session.get(Lead, lead_id)
        (await session.get(Comment, lead.comment_id)).text = "=1+1"
        (await session.get(Contact, lead.contact_id)).display_name = "=1+1"
        await session.commit()
    app = _build_test_app(_dev_settings(web_manager_id=1001), session_factory)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://testserver") as client:
        response = await client.get("/api/leads/export.csv")
    assert response.status_code == 200
    row = next(csv.DictReader(io.StringIO(response.text)))
    assert row["comment"] == row["display_name"] == "'=1+1"


@pytest.mark.parametrize("user_id,expected", [(202, 403), (303, 403), (101, 409)])
async def test_budget_reconciliation_requires_admin(session_factory, user_id, expected):
    settings = _secured_settings()
    auth = TelegramWebAuth(settings)
    token = auth.create_session(user_id)
    app = _build_test_app(settings, session_factory)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://testserver",
        cookies={auth.COOKIE_NAME: token},
    ) as client:
        response = await client.post(
            "/api/budget/reservations/999/reconcile", json={"spent": False},
            headers={"X-CSRF-Token": auth.create_csrf_token(token)},
        )
    assert response.status_code == expected
