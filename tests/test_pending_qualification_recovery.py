import re
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.config import Settings
from app.db.models import AIFeedback, Competitor, ContactEvent, Lead, LeadStatus, Post
from app.schemas.leads import Intent
from app.services.ai_context_fingerprint_service import AIContextFingerprintService
from app.services.ai_service import LeadAnalysisContext, RuleBasedLeadAnalyzer
from app.services.contact_service import ContactService
from app.services.instagram_monitor import CycleStats
from app.services.lead_service import LeadService
from app.services.lead_workflow_service import LeadWorkflowService
from app.services.monitor_controller import MonitorController
from app.services.usage_service import ExternalBudgetExceeded, ExternalUsageService
from app.web.app import build_web_app
from app.web.queries import WebQueryService
from tests.test_contact_service import make_comment, make_post


def context(text, *, caption="Buyurtma berish uchun", source="FURNITURE"):
    return LeadAnalysisContext(
        competitor="furniture_source", post_caption=caption, comment=text,
        username="public_buyer", previous_signals=[], previous_interests=[],
        source_vertical=source,
    )


@pytest.mark.parametrize("text,intent", [
    ("narh", Intent.PRICE), ("Катологчи", Intent.CATALOG),
    ("Можно даставку", Intent.DELIVERY), ("Narxi nechpul", Intent.PRICE),
    ("Adres", Intent.LOCATION), ("Борми шу модель дан", Intent.AVAILABILITY),
    ("Можно прайс и размер пожалуйста", Intent.SIZE),
    ("Narhı nıshpul", Intent.PRICE), ("Заказ килмокчи эдим", Intent.BUY),
    ("Нархи канча асалим  ёзворинг", Intent.PRICE),
    ("10 kishilogi bormi nechpul", Intent.PRICE),
])
def test_screenshot_commercial_requests_are_hot_without_gpt(text, intent):
    analysis = RuleBasedLeadAnalyzer().classify(context(text))
    assert analysis is not None and analysis.is_lead
    assert analysis.intent == intent and analysis.lead_score >= 70
    # A configured furniture source establishes relevance, not an invented SKU.
    assert analysis.product_category is None


async def test_local_reanalysis_corrects_legacy_price_score_without_paid_analyzer(session_factory):
    analyzer = BudgetBlockedAnalyzer()
    service = LeadService(session_factory, analyzer, 70, rules_version="3.3")
    result = await pending_signal(
        session_factory, service, "Нархи канча асалим  ёзворинг", "legacy-price")
    async with session_factory() as session:
        source = await session.scalar(select(Competitor))
        source.active = True
        post = await session.scalar(select(Post))
        post.caption = "Buyurtma berish uchun"
        lead = await session.get(Lead, result.lead_id)
        lead.status = LeadStatus.NEW
        lead.intent = Intent.PRICE.value
        lead.lead_score = 60
        lead.ai_source = "openai_or_cache"
        lead.analysis_details = {"rules_version": "3.2", "priority_score": 7}
        await session.commit()
        before = [(e.id, e.event_type, e.payload_json) for e in await session.scalars(
            select(ContactEvent).order_by(ContactEvent.id))]
        lead_count = await session.scalar(select(func.count(Lead.id)))
    calls_before = analyzer.calls
    corrected = await service.analyze_lead(result.lead_id, local_only=True)
    assert corrected.status == LeadStatus.NEW and corrected.is_hot and corrected.score == 78
    assert analyzer.calls == calls_before
    async with session_factory() as session:
        lead = await session.get(Lead, result.lead_id)
        assert lead.ai_source == "local_rules" and lead.product_category is None
        assert lead.analysis_details["rules_version"] == "3.3"
        assert lead.analysis_details["priority_score"] == lead.lead_score
        assert await session.scalar(select(func.count(Lead.id))) == lead_count
        after = [(e.id, e.event_type, e.payload_json) for e in await session.scalars(
            select(ContactEvent).order_by(ContactEvent.id))]
        assert after[:len(before)] == before and len(after) > len(before)


@pytest.mark.parametrize("text", ["narh", "Narxi nechpul", "Adres", "Катологчи"])
def test_generic_request_without_configured_source_still_needs_context(text):
    assert RuleBasedLeadAnalyzer().classify(context(text, source=None)) is None


@pytest.mark.parametrize("caption", ["Rolex soatlar", "Новые кроссовки", "Ноутбук в продаже"])
def test_source_vertical_does_not_override_explicit_unrelated_product(caption):
    analysis = RuleBasedLeadAnalyzer().classify(context("Narh qancha?", caption=caption))
    assert analysis is not None and not analysis.is_lead and analysis.lead_score < 70


@pytest.mark.parametrize("text", [
    "Bu narhlar mavjud emas, aldayaptilar", "Почему закрываетесь?",
    "Заказ килмокчи эмасман", "zakaz qilmoqchi emasman",
])
def test_aliases_preserve_negative_purchase_and_complaint_guards(text):
    analysis = RuleBasedLeadAnalyzer().classify(context(text, caption="Диван"))
    assert analysis is not None and not analysis.is_lead and analysis.lead_score < 70


def test_source_direction_is_part_of_semantic_fingerprint():
    fingerprints = AIContextFingerprintService(
        analysis_version="3.3", model="test", prompt_version="test", schema_version="test")
    original = context("narh", source=None)
    configured = replace(original, source_vertical="FURNITURE")
    assert fingerprints.fingerprint(original) != fingerprints.fingerprint(configured)
    assert fingerprints.fingerprint(configured) == fingerprints.fingerprint(configured)


class BudgetBlockedAnalyzer:
    calls = 0

    async def analyze(self, context):
        self.calls += 1
        raise ExternalBudgetExceeded("Daily AI budget reached")


async def pending_signal(session_factory, service, text, index):
    signal = await ContactService(session_factory).persist_signal(
        make_post(), make_comment(f"pending-{index}").model_copy(update={
            "username": f"public_{index}", "platform_user_id": f"public-id-{index}",
            "text": text, "created_at": datetime.now(UTC)}))
    return await service.process_signal(signal)


async def test_local_recovery_uses_source_context_and_preserves_history_and_ambiguity(session_factory):
    analyzer = BudgetBlockedAnalyzer()
    service = LeadService(session_factory, analyzer, 70)
    first = await pending_signal(session_factory, service, "narh", 1)
    second = await pending_signal(session_factory, service, "Непонятный комментарий", 2)
    async with session_factory() as session:
        source = await session.scalar(select(Competitor))
        source.active = True
        # The source direction is used when captions contain no product keywords.
        post = await session.scalar(select(Post))
        post.caption = "Buyurtma berish uchun"
        await session.commit()
        before = [(e.id, e.event_type, e.payload_json) for e in await session.scalars(
            select(ContactEvent).order_by(ContactEvent.id))]
    assert first.status == second.status == LeadStatus.AI_PENDING
    calls_before = analyzer.calls
    results = await service.retry_pending_local()
    assert analyzer.calls == calls_before
    assert [r.lead_id for r in results] == [first.lead_id]
    assert results[0].status == LeadStatus.NEW and results[0].is_hot
    async with session_factory() as session:
        unclear = await session.get(Lead, second.lead_id)
        assert unclear.status == LeadStatus.AI_PENDING and unclear.ai_attempt_count == 1
        after = [(e.id, e.event_type, e.payload_json) for e in await session.scalars(
            select(ContactEvent).order_by(ContactEvent.id))]
        assert after[:len(before)] == before
        assert await session.scalar(select(func.count(AIFeedback.id))) == 1
    assert not await service.retry_pending_local()
    async with session_factory() as session:
        repeated = [(e.id, e.event_type, e.payload_json) for e in await session.scalars(
            select(ContactEvent).order_by(ContactEvent.id))]
        assert repeated == after


class IdleMonitor:
    provider = None

    async def run_cycle(self, **kwargs):
        return CycleStats()


async def test_pending_card_shows_unfinished_analysis_instead_of_zero_priority(session_factory):
    service = LeadService(session_factory, BudgetBlockedAnalyzer(), 70)
    pending = await pending_signal(session_factory, service, "Неоднозначно", 3)
    app = build_web_app(
        Settings(_env_file=None, web_enabled=True), WebQueryService(session_factory, hot_threshold=70),
        LeadWorkflowService(session_factory, 70), MonitorController(IdleMonitor()),
        ExternalUsageService(session_factory))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/radar?kind=pending")
    assert response.status_code == 200
    card = re.search(
        rf'<article\b[^>]*data-lead-id="{pending.lead_id}"[^>]*>(.*?)</article>', response.text, re.S)
    assert card is not None
    text = card.group(1)
    assert "Оценка ещё не рассчитана" in text and "достигнут лимит AI" in text
    assert "Приоритет 0/100" not in text and "Другое" not in text
