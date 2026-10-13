"""Paid delivery accounting and the manual new-lead search contract."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.config import Settings
from app.db.models import (
    Comment,
    Competitor,
    ContactEvent,
    ExternalBudgetReservation,
    ExternalUsage,
    Lead,
    LeadStatus,
    MonitorRun,
    MonitorRunStatus,
    ReservationStatus,
)
from app.providers.base import ProviderCallUncertainError, ProviderError, ProviderUsageBlockedError
from app.providers.brightdata import BrightDataProvider
from app.providers.budgeted import BudgetedInstagramProvider, ScanBudget
from app.providers.fallback import FallbackInstagramProvider
from app.providers.mock import MockInstagramProvider
from app.providers.scrapecreators import ScrapeCreatorsProvider
from app.schemas.instagram import InstagramComment, InstagramPost
from app.schemas.leads import Intent
from app.services.ai_service import LeadAnalysisContext, RuleBasedLeadAnalyzer
from app.services.contact_service import ContactService
from app.services.instagram_monitor import CycleStats
from app.services.lead_service import LeadService
from app.services.lead_workflow_service import LeadWorkflowService
from app.services.monitor_controller import MonitorController
from app.services.operational_control_service import OperationalControlService
from app.services.provider_credit_budget_service import ProviderCreditBudgetService
from app.services.usage_service import ExternalBudgetExceeded, ExternalUsageService
from app.web.app import build_web_app
from app.web.queries import WebQueryService
from tests.conftest import seed_scrapecreators_instagram_policy


def post():
    return InstagramPost(platform_post_id="search-preparation", competitor="aiko.uz",
        url="https://www.instagram.com/p/search-preparation/", caption="Плетёные стулья. Распродажа.",
        published_at=datetime.now(UTC), comments_count=2)


def failure_response(request, failure):
    if failure == "timeout":
        raise httpx.ReadTimeout("simulated lost response", request=request)
    return httpx.Response(int(failure), json={"error": "simulated failure"})


@pytest.mark.parametrize("provider_name", ["scrapecreators", "brightdata"])
@pytest.mark.parametrize("operation", ["get_profile", "get_reels", "get_post", "get_comment_batch"])
@pytest.mark.parametrize("failure", ["500", "429", "timeout"])
async def test_paid_adapters_deliver_only_one_attempt(provider_name, operation, failure):
    requests = []

    def respond(request):
        requests.append(request)
        return failure_response(request, failure)

    async with AsyncClient(transport=httpx.MockTransport(respond)) as client:
        if provider_name == "scrapecreators":
            provider = ScrapeCreatorsProvider("test-only", max_attempts=5, client=client)
        else:
            provider = BrightDataProvider("test-only", api_url="https://provider.test/scrape",
                profile_dataset_id="profile", posts_dataset_id="posts", reels_dataset_id="reels",
                comments_dataset_id="comments", max_attempts=5, client=client)
        with pytest.raises(ProviderError):
            if operation == "get_profile":
                await provider.get_profile("aiko.uz")
            elif operation == "get_reels":
                await provider.get_reels("aiko.uz")
            elif operation == "get_post":
                await provider.get_post(post().url, "aiko.uz")
            else:
                await provider.get_comment_batch(post(), max_pages=1)
    assert len(requests) == 1


@pytest.mark.parametrize("failure", ["500", "429", "timeout"])
async def test_failed_comment_delivery_is_uncertain_and_blocks_retry_and_fallback(
    session_factory, failure,
):
    await seed_scrapecreators_instagram_policy(session_factory)
    requests = []

    def respond(request):
        requests.append(request)
        return failure_response(request, failure)

    usage = ExternalUsageService(session_factory)
    budget = ScanBudget(1)
    fallback = MockInstagramProvider()
    fallback.get_comment_batch = AsyncMock()
    async with AsyncClient(transport=httpx.MockTransport(respond)) as client:
        primary = BudgetedInstagramProvider(
            ScrapeCreatorsProvider("test-only", max_attempts=3, client=client),
            usage, enabled=True, daily_limit=100, scan_budget=budget,
        )
        chain = FallbackInstagramProvider(primary, fallback)
        with pytest.raises(ProviderCallUncertainError):
            await chain.get_comment_batch(post(), max_pages=1)
        assert budget.used == 1
        # A fresh manual budget must not erase the unresolved delivered request.
        primary.set_scan_budget_limit(5)
        with pytest.raises(ProviderUsageBlockedError):
            await chain.get_comment_batch(post(), max_pages=1)
    assert len(requests) == 1
    fallback.get_comment_batch.assert_not_awaited()
    async with session_factory() as session:
        reservation = await session.scalar(select(ExternalBudgetReservation))
        assert reservation.status == ReservationStatus.UNCERTAIN
        assert reservation.units_reserved == 1
        assert reservation.call_started_at is not None
        assert await session.scalar(select(func.count(ExternalBudgetReservation.id))) == 1
        assert await session.scalar(select(func.count(ExternalUsage.id))) == 0


@pytest.mark.parametrize("status", [ReservationStatus.UNCERTAIN, ReservationStatus.EXPIRED, ReservationStatus.RESERVED])
async def test_unresolved_old_delivery_blocks_preview_and_atomic_reservation(session_factory, status):
    await seed_scrapecreators_instagram_policy(session_factory)
    old = datetime.now(UTC) - timedelta(days=40)
    async with session_factory() as session:
        session.add(ExternalBudgetReservation(reservation_key="old-delivery",service="instagram",
            provider="scrapecreators",operation="get_comments",units_reserved=1,status=status,
            call_started_at=old,expires_at=old+timedelta(seconds=60),created_at=old,reserved_at=old))
        await session.commit()
    usage = ExternalUsageService(session_factory)
    preview = await ProviderCreditBudgetService(session_factory).available_for_scan(
        provider="scrapecreators",requested_units=5,daily_remaining=100)
    assert preview.effective_units == 0 and preview.blocking_reasons
    with pytest.raises(ExternalBudgetExceeded, match="не подтверждён"):
        await usage.reserve_budget("instagram","get_comments",100,provider="scrapecreators",enforce_daily_limit=False)
    queries = WebQueryService(session_factory, hot_threshold=70)
    queue = await queries.uncertain_external_reservation_queue()
    assert len(queue) == 1
    assert (await queries.ai_safety_diagnostics())["uncertain_reservations"] == 1
    async with session_factory() as session:
        assert await session.scalar(select(func.count(ExternalBudgetReservation.id))) == 1
    assert await usage.reconcile_uncertain_reservation(queue[0]["reservation_id"], spent=False)
    assert not await queries.uncertain_external_reservation_queue()
    assert not await usage.unresolved_deliveries("instagram")


async def test_manual_reconciliation_allows_a_new_delivered_request(session_factory):
    await seed_scrapecreators_instagram_policy(session_factory)
    usage = ExternalUsageService(session_factory)
    reservation = await usage.reserve_budget("instagram","get_comments",100,provider="scrapecreators")
    await usage.mark_call_started(reservation)
    await usage.mark_reservation_uncertain(reservation)
    assert await usage.reconcile_uncertain_reservation(reservation,spent=False)
    preview = await ProviderCreditBudgetService(session_factory).available_for_scan(
        provider="scrapecreators",requested_units=5,daily_remaining=100)
    assert preview.effective_units == 5 and not preview.blocking_reasons
    new = await usage.reserve_budget("instagram","get_comments",100,provider="scrapecreators")
    assert new != reservation


@pytest.mark.parametrize("text", [
    "Алдаяптилар , бунака нархлар мавжуд эмас бу магазинда !!!",
    "Bu narxlar mavjud emas, aldayaptilar!",
    "Bu narxlar yo‘q do'konda",
    "Обманывают, таких цен нет в магазине!",
    "Цена не соответствует рекламе",
    "Почему ликвидация? Закрываетесь что-ли?",
    "Do'kon yopilyaptimi?",
    "Почему доставка так долго?",
])
async def test_complaints_and_why_questions_are_not_hot_buyers(text):
    result = await RuleBasedLeadAnalyzer().analyze(LeadAnalysisContext(
        competitor="aiko.uz", post_caption=post().caption, comment=text, username="public_test",
        previous_signals=[], previous_interests=[],
    ))
    if text == "Почему доставка так долго?":
        # A delivery question is actionable, but must never be mistaken for PRICE.
        assert result.intent != Intent.PRICE
    else:
        assert not result.is_lead
        assert result.lead_score < 70
        assert result.intent == Intent.OTHER


@pytest.mark.parametrize("text,intent", [
    ("Почём плетёный стул?", Intent.PRICE), ("почем?", Intent.PRICE),
    ("Цена?", Intent.PRICE), ("Narxi qancha?", Intent.PRICE),
    ("Нархи қанча?", Intent.PRICE),
    ("Хочу купить плетёный стул", Intent.BUY),
    ("Обманывают? Но хочу купить плетёный стул, какая цена?", Intent.BUY),
    ("Ликвидация? Сколько стоит плетёный стул?", Intent.PRICE),
])
async def test_real_purchase_questions_remain_actionable(text, intent):
    result = await RuleBasedLeadAnalyzer().analyze(LeadAnalysisContext(
        competitor="aiko.uz", post_caption=post().caption, comment=text, username="public_test",
        previous_signals=[], previous_interests=[],
    ))
    assert result.is_lead and result.lead_score >= 70
    assert result.intent == intent


async def test_new_comments_are_classified_and_repeat_ingestion_preserves_history(session_factory):
    contacts = ContactService(session_factory)
    leads = LeadService(session_factory, RuleBasedLeadAnalyzer(), hot_threshold=70)
    saved = []
    for index, text in enumerate(["Обманывают, таких цен нет!", "Хочу купить плетёный стул"]):
        comment = InstagramComment(platform_comment_id=f"new-comment-{index}", username=f"public_{index}",
            profile_url=f"https://www.instagram.com/public_{index}/", text=text, created_at=datetime.now(UTC))
        signal = await contacts.persist_signal(post(), comment)
        result = await leads.process_signal(signal)
        saved.append((comment, result))
    assert not saved[0][1].is_hot
    assert saved[1][1].is_hot
    async with session_factory() as session:
        events_before = list(await session.scalars(select(ContactEvent).order_by(ContactEvent.id)))
        expected = [(e.id, e.event_type, e.payload_json) for e in events_before]
    for comment, previous in saved:
        signal = await contacts.persist_signal(post(), comment)
        result = await leads.process_signal(signal)
        assert not signal.created and result is None
        async with session_factory() as session:
            assert await session.scalar(select(Lead.id).where(Lead.comment_id == signal.comment_id)) == previous.lead_id
    async with session_factory() as session:
        assert await session.scalar(select(func.count(Comment.id))) == 2
        assert await session.scalar(select(func.count(Lead.id))) == 2
        assert set(await session.scalars(select(Lead.status))) == {LeadStatus.NEW, LeadStatus.NOT_LEAD}
        events_after = list(await session.scalars(select(ContactEvent).order_by(ContactEvent.id)))
        assert [(e.id, e.event_type, e.payload_json) for e in events_after] == expected


class CountingMonitor:
    provider = None
    calls = 0

    async def run_cycle(self, **kwargs):
        self.calls += 1
        return CycleStats()


async def test_empty_live_vertical_cannot_start_and_last_run_is_labelled_global(session_factory):
    await seed_scrapecreators_instagram_policy(session_factory)
    async with session_factory() as session:
        session.add(Competitor(handle="aiko.uz", normalized_handle="aiko.uz", active=True))
        session.add(MonitorRun(trigger="web", status=MonitorRunStatus.SUCCESS,
            stats_json={"comments_created":17,"leads_created":17}, actual_credits_spent=5))
        await session.commit()
    settings = Settings(_env_file=None, lead_search_enabled=True, web_enabled=True,
        instagram_provider="scrapecreators", instagram_live_calls_enabled=True,
        external_live_unlock="ALLOW_EXTERNAL_CALLS", external_kill_switch=False, web_manager_id=1001)
    ops = OperationalControlService(session_factory)
    await ops.load()
    await ops.set_radar_live(True, manager_id=1001)
    monitor = CountingMonitor()
    controller = MonitorController(monitor)
    app = build_web_app(settings, WebQueryService(session_factory, hot_threshold=70),
        LeadWorkflowService(session_factory, hot_threshold=70), controller,
        ExternalUsageService(session_factory), ops_control=ops)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        furniture = (await client.get("/api/scan/preview?vertical=FURNITURE")).json()
        rattan = (await client.get("/api/scan/preview?vertical=ARTIFICIAL_RATTAN")).json()
        blocked = await client.post("/api/scan", json={"confirm_live":True,"max_credits":5,"vertical":"ARTIFICIAL_RATTAN"})
        page = await client.get("/radar?vertical=ARTIFICIAL_RATTAN")
    assert furniture["can_start"] and furniture["active_competitors"] == 1
    assert not rattan["can_start"] and rattan["active_competitors"] == 0
    assert "нет активных Instagram-источников" in " ".join(rattan["blocking_reasons"])
    assert rattan["estimated_comment_pages"] == 0
    assert blocked.status_code == 409 and monitor.calls == 0
    assert "Последний запуск системы" in page.text
    assert "Общая статистика последнего запуска" in page.text
    assert 'type="button" data-scan disabled' in page.text
