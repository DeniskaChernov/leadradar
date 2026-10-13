import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.db.models import ContactEvent, InterestEvidence, Lead, LeadStatus
from app.schemas.leads import Intent, LeadAnalysis
from app.services.ai_service import LeadAnalysisContext, RuleBasedLeadAnalyzer
from app.services.audience_service import AudienceEngine
from app.services.contact_service import ContactService
from app.services.lead_service import LeadService
from app.services.next_best_action_service import NextBestActionEngine
from app.services.product_context_service import resolve_product_context
from tests.test_contact_service import make_comment, make_post
from tests.test_openings_and_hot_pagination import _hot, _hot_web_app


@pytest.mark.parametrize("comment,caption,category", [
    ("Shu 399 minlik divandan 2 dona dastafka qilib berin", "Кресло Criptos", "SOFA"),
    ("кровать2 та нарх канака", "Кресло, кровать и стол", "BED"),
    ("Karavot narxi?", "Кресло LEO", "BED"),
    ("Хочу диван", "Обеденный комплект", "SOFA"),
    ("stul narxi", "Диван", "CHAIRS"),
    ("Kreslosi qancha", "Диван и стол", "ARMCHAIR"),
    ("table price?", "Armchair", "TABLE"),
    ("sofa price?", "Table", "SOFA"),
    ("bed price?", "Chair", "BED"),
    ("2 та диван бн 1 та кресло доставка килиб бесила", "Кресло", "MIXED_FURNITURE"),
    ("Диван и стол нужны", "Обеденный комплект", "MIXED_FURNITURE"),
    ("Нархи?", "Диван угловой Aura", "SOFA"),
    ("Цена", "Кресло, кровать, стол", None),
    ("Цена", "Обеденный комплект: стол и стулья", "DINING_SET"),
    ("Борми сотувда?", "Овқатланиш столлари", "TABLE"),
    ("Ротанговый диван нархи", "Стол", "RATTAN_SOFA"),
    ("Плетеное кресло цена", "Диван", "RATTAN_ARMCHAIR"),
    ("Rattan table price", "Chair", "RATTAN_TABLE"),
    ("Цена", "Rattan garden set", "RATTAN_GARDEN_SET"),
    ("Rattan bar stool price", "", "RATTAN_BAR_STOOL"),
    ("Высокий стул цена", "", "RATTAN_BAR_STOOL"),
    ("Качели цена", "Кресло", "SWING"),
    ("Пергола цена", "Кресло", "PERGOLA"),
    ("Chairman bedtime story", "", None),
    ("Адрес?", "Акция на всю мебель", None),
])
def test_explicit_product_has_priority_over_publication(comment, caption, category):
    assert resolve_product_context(comment, caption).category == category


def test_parent_product_is_used_before_caption_for_a_short_reply():
    result = resolve_product_context("Цена?", "Кресло", "Можно заказать диван?")
    assert result.category == "SOFA"
    assert result.source == "PARENT_COMMENT"


def test_mixed_order_keeps_each_family_but_not_a_misleading_single_quantity():
    context = LeadAnalysisContext(
        competitor="aiko.uz", post_caption="Кресло Criptos",
        comment="2 та диван бн 1 та кресло доставка килиб бесила.", username="buyer",
        previous_signals=[], previous_interests=[],
    )
    result = RuleBasedLeadAnalyzer().classify(context)
    assert result and result.is_lead
    assert result.product_category == "MIXED_FURNITURE"
    assert result.quantity is None
    assert resolve_product_context(context.comment, context.post_caption).categories == (
        "SOFA", "ARMCHAIR",
    )
    recommendation = NextBestActionEngine.recommend(
        buyer_role="B2C_CONSUMER", intent="QUANTITY", product_category=result.product_category,
        lead_score=result.lead_score,
    )
    assert recommendation.action_type == "CLARIFY_PRODUCTS"
    assert recommendation.recommended_product_id is None


class WrongProductAnalyzer:
    async def analyze(self, context):
        return LeadAnalysis(is_lead=True, lead_score=91, intent=Intent.PRICE,
                            product_category="CHAIRS", language="ru", reason="Price request")


async def _stored_lead(factory, *, mixed=False):
    text = "2 та диван бн 1 та кресло доставка килиб бесила" if mixed else "Диван цена?"
    signal = await ContactService(factory).persist_signal(
        make_post().model_copy(update={"caption": "Кресло, кровать, стол"}),
        make_comment().model_copy(update={"text": text}),
    )
    service = LeadService(factory, WrongProductAnalyzer(), 70)
    result = await service.process_signal(signal)
    return service, result.lead_id, signal.contact_id


async def test_explicit_product_corrects_analyzer_output_and_persisted_details(session_factory):
    _, lead_id, _ = await _stored_lead(session_factory)
    async with session_factory() as session:
        lead = await session.get(Lead, lead_id)
        assert lead.product_category == lead.analysis_details["product_category"] == "SOFA"
        assert lead.analysis_details["product_context"]["source"] == "COMMENT"


async def test_hot_mixed_product_families_reach_the_card_and_draft_context(session_factory):
    _, lead_id, _ = await _stored_lead(session_factory, mixed=True)
    detail = await _hot(session_factory).detail(lead_id)
    assert detail["product_category"] == "MIXED_FURNITURE"
    assert detail["product_categories"] == ["SOFA", "ARMCHAIR"]
    app = _hot_web_app(session_factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/hot?vertical=FURNITURE&lead_id={lead_id}")
    assert response.status_code == 200
    detail_html = response.text.split('data-hot-detail>', 1)[1]
    assert "Несколько товаров · Диван · Кресло" in detail_html
    assert "Уточнить позиции заказа" in detail_html


@pytest.mark.parametrize("mixed", [False, True])
async def test_product_repair_is_idempotent_and_preserves_workflow_and_contact_history(
    session_factory, mixed,
):
    service, lead_id, contact_id = await _stored_lead(session_factory, mixed=mixed)
    engine = AudienceEngine(session_factory, hot_threshold=70)
    service.audience_engine = engine
    async with session_factory() as session:
        lead = await session.get(Lead, lead_id)
        lead.product_category = "CHAIRS"
        lead.status = LeadStatus.TAKEN
        lead.assigned_manager_telegram_id = 101
        lead.analysis_details = {**lead.analysis_details, "product_category": "CHAIRS",
                                 "product_context": {}, "quantity": 2}
        await session.commit()
        before = [(event.id, dict(event.payload_json)) for event in
                  await session.scalars(select(ContactEvent).order_by(ContactEvent.id))]
    await engine.recalculate_contact(contact_id)
    first = await service.repair_product_contexts()
    second = await service.repair_product_contexts()
    assert first["updated"] == [lead_id] and second["updated"] == []
    assert first["pending_contacts"] == []
    async with session_factory() as session:
        lead = await session.get(Lead, lead_id)
        assert lead.product_category == ("MIXED_FURNITURE" if mixed else "SOFA")
        assert lead.status == LeadStatus.TAKEN
        assert lead.assigned_manager_telegram_id == 101
        assert lead.lead_score == 91
        after = [(event.id, dict(event.payload_json)) for event in
                 await session.scalars(select(ContactEvent).order_by(ContactEvent.id))]
        assert after[:len(before)] == before
        assert len(after) == len(before) + 1
        topics = set(await session.scalars(select(InterestEvidence.topic).where(
            InterestEvidence.contact_id == contact_id, InterestEvidence.dimension == "PRODUCT",
            InterestEvidence.active.is_(True),
        )))
        assert topics == ({"SOFA", "ARMCHAIR"} if mixed else {"SOFA"})


async def test_product_repair_retries_audience_failure_without_duplicating_history(session_factory):
    service, lead_id, _ = await _stored_lead(session_factory)
    async with session_factory() as session:
        lead = await session.get(Lead, lead_id)
        lead.product_category = "CHAIRS"
        await session.commit()

    class FlakyAudience:
        failed = False

        async def recalculate_contact(self, contact_id):
            if not self.failed:
                self.failed = True
                raise RuntimeError("temporary failure")

    service.audience_engine = FlakyAudience()
    first = await service.repair_product_contexts()
    second = await service.repair_product_contexts()
    assert first["pending_contacts"] and not second["pending_contacts"]
    assert second["updated"] == []
    async with session_factory() as session:
        lead = await session.get(Lead, lead_id)
        assert lead.analysis_details["product_context_audience_pending"] is False
        assert await session.scalar(select(func.count(ContactEvent.id)).where(
            ContactEvent.event_type == "QUALIFICATION_UPDATED",
        )) == 1
