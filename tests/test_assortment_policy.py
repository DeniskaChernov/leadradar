import json
from pathlib import Path

import pytest
from sqlalchemy import select

from app.db.models import (
    Competitor,
    ContactEvent,
    Lead,
    LeadStatus,
    NotificationPolicy,
    Product,
    Vertical,
)
from app.schemas.leads import Intent, LeadAnalysis
from app.services.ai_service import HybridLeadAnalyzer, LeadAnalysisContext, RuleBasedLeadAnalyzer
from app.services.assortment_policy import apply_assortment, assess_assortment
from app.services.audience_service import AudienceEngine
from app.services.contact_service import ContactService
from app.services.lead_service import LeadService
from app.services.lead_workflow_service import LeadWorkflowService
from app.services.notification_eligibility import eligible_policy_clause
from app.services.product_catalog_service import ProductCatalogService
from app.services.public_catalog_import_service import import_btt_snapshot
from app.web.queries import WebQueryService
from scripts.repair_assortment import repair_catalog
from tests.test_contact_service import make_comment, make_post
from tests.test_openings_and_hot_pagination import _hot


@pytest.fixture
def btt_snapshot():
    return json.loads((Path(__file__).parents[1] / "app/data/btt_public_catalog_2026-10-06.json").read_text(encoding="utf-8"))


def context(text, caption="Обеденный комплект"):
    return LeadAnalysisContext(competitor="aiko.uz", comment=text, post_caption=caption,
                               username="buyer", previous_interests=[], previous_signals=[])


@pytest.mark.parametrize("text,caption", [
    ("Диван цена?", "Плетёная мебель"), ("Ротанговый диван для кафе нужен", "Мебель для HoReCa"),
    ("Komod narxi?", "Стулья"), ("Компьютерный стол купить", "Обеденный комплект"),
    ("Kompyuter stoli qancha", "Плетёная мебель"), ("Karavot narxi?", "Обеденный комплект"),
    ("Цена?", "Диван Aura"), ("Офисное кресло цена", "Ротанг"),
])
async def test_unsupported_product_bypasses_openai_even_in_openai_mode(text, caption):
    class MustNotCall:
        async def analyze(self, _context):
            raise AssertionError("Off-assortment signals must not spend AI credits")
    result, source = await HybridLeadAnalyzer(RuleBasedLeadAnalyzer(), MustNotCall(), mode="openai").analyze_with_source(context(text, caption))
    assert source == "local_rules"
    assert result.is_lead is False and result.lead_score == result.priority_score == 0
    assert result.is_commercial is False


@pytest.mark.parametrize("text,caption,category", [
    ("Пластиковые стулья цена?", "Мебель", "PLASTIC_CHAIRS"),
    ("Обеденные стулья купить", "Мебель", "DINING_CHAIRS"),
    ("Плетёное кресло цена", "Мебель", "RATTAN_ARMCHAIR"),
    ("Кресло цена", "Мебель из искусственного ротанга", "RATTAN_ARMCHAIR"),
    ("Ratan stul narxi", "Мебель", "RATTAN_CHAIR"),
    ("Стул цена?", "Диван", "CHAIRS"),
    ("Цена?", "Обеденный комплект: стол и стулья", "DINING_SET"),
])
def test_supported_assortment_remains_commercial(text, caption, category):
    assert assess_assortment(text, caption).status == "MATCH"
    result = RuleBasedLeadAnalyzer().classify(context(text, caption))
    assert result and result.is_lead and result.product_category == category


def test_generic_armchair_and_partial_orders_require_clarification():
    result = RuleBasedLeadAnalyzer().classify(context("Кресло цена?", "Кресло"))
    assert result and result.is_lead and result.lead_score <= 60 and not result.is_commercial
    assert assess_assortment("Диван и пластиковые стулья нужны", "Мебель").status == "REVIEW"
    assert assess_assortment("Ротанг для производства", "Сырьё", vertical="ARTIFICIAL_RATTAN").status == "OTHER_VERTICAL"


@pytest.mark.parametrize("comment", ["Кресло цена?", "Диван цена?"])
def test_repeated_assortment_guard_is_idempotent(comment):
    analysis = LeadAnalysis(is_lead=True, lead_score=90, intent=Intent.PRICE,
                            product_category=None, language="ru", reason="Price",
                            recommended_action="Уточнить количество.")
    decision = assess_assortment(comment, "Мебель")
    first = apply_assortment(analysis, decision)
    assert apply_assortment(first, decision) == first


@pytest.mark.parametrize("comment,status,category", [
    ("Нужен комплект ротанг с диваном", "EXCLUDED", "RATTAN_SOFA"),
    ("Комплект ротанг: кресло и диван для кафе", "REVIEW", "RATTAN_SOFA"),
    ("Барные стулья и диван цена", "REVIEW", "SOFA"),
])
def test_set_and_bar_stool_labels_do_not_hide_unsupported_products(comment, status, category):
    decision = assess_assortment(comment, "Мебель для HoReCa")
    assert decision.status == status and category in decision.categories


async def test_saved_repair_is_local_idempotent_and_keeps_manager_workflow(session_factory):
    class Analyzer:
        async def analyze(self, _context):
            return LeadAnalysis(is_lead=True, lead_score=90, intent=Intent.PRICE,
                                product_category="CHAIRS", language="ru", reason="Buy")
    signal = await ContactService(session_factory).persist_signal(
        make_post().model_copy(update={"caption": "Диван"}),
        make_comment().model_copy(update={"text": "Цена?"}),
    )
    service = LeadService(session_factory, Analyzer(), 70)
    processed = await service.process_signal(signal)
    async with session_factory() as session:
        lead = await session.get(Lead, processed.lead_id)
        assert lead.status == LeadStatus.NOT_LEAD  # Guard also covers a custom analyzer.
        lead.status = LeadStatus.TAKEN
        lead.assigned_manager_telegram_id = 101
        lead.lead_score = 90
        lead.analysis_details = {"confidence": 90}
        await session.commit()
        history = [(event.id, event.payload_json) for event in await session.scalars(select(ContactEvent).order_by(ContactEvent.id))]
    preview = await service.repair_assortment()
    assert preview["excluded"] == [lead.id]
    first = await service.repair_assortment(dry_run=False)
    second = await service.repair_assortment(dry_run=False)
    assert first["updated"] == [lead.id] and second["updated"] == []
    async with session_factory() as session:
        saved = await session.get(Lead, lead.id)
        assert saved.status == LeadStatus.TAKEN and saved.assigned_manager_telegram_id == 101
        assert saved.lead_score == 0
        after = [(event.id, event.payload_json) for event in await session.scalars(select(ContactEvent).order_by(ContactEvent.id))]
        assert after[:len(history)] == history and len(after) == len(history) + 1


async def test_catalog_material_matching_and_retirement_are_idempotent(session_factory, btt_snapshot):
    service = ProductCatalogService(session_factory)
    await import_btt_snapshot(service, btt_snapshot, manager_id=101, apply=True)
    plastic = await service.matching_products(vertical=Vertical.FURNITURE, category="PLASTIC_CHAIRS")
    wicker = await service.matching_products(vertical=Vertical.FURNITURE, category="RATTAN_CHAIR")
    assert len(plastic) == 5 and len(wicker) == 2
    assert not {p.id for p in plastic} & {p.id for p in wicker}
    assert await service.matching_products(vertical=Vertical.FURNITURE, category="SOFA") == []
    assert await repair_catalog(service, btt_snapshot, manager_id=101, apply=True) == []
    assert all(p.category != "LAMP" for p in await service.products())


async def test_legacy_catalog_repair_preserves_prices_stock_and_raw_material_direction(session_factory, btt_snapshot):
    service = ProductCatalogService(session_factory)
    await service.sync_confirmed_catalog()
    async with session_factory() as session:
        seeds = list(await session.scalars(select(Product)))
        for product in seeds:
            product.vertical = Vertical.ARTIFICIAL_RATTAN  # Reproduce the old incorrect seed direction.
        lamp = Product(canonical_key="old-lamp", name="Лампа", vertical=Vertical.FURNITURE,
                       category="LAMP", active=True, price=100, stock=2, currency="UZS")
        session.add(lamp)
        await session.commit()
        before = {p.id: (p.price, p.stock, p.cogs) for p in await session.scalars(select(Product))}
    changes = await repair_catalog(service, btt_snapshot, manager_id=101, apply=True)
    assert len(changes) == len(seeds) + 1
    assert await repair_catalog(service, btt_snapshot, manager_id=101, apply=True) == []
    async with session_factory() as session:
        products = list(await session.scalars(select(Product)))
        assert {p.id: (p.price, p.stock, p.cogs) for p in products} == before
        assert all(p.vertical == Vertical.FURNITURE for p in products)
        assert not (await session.get(Product, lamp.id)).active


@pytest.mark.parametrize("assortment_status", ["REVIEW", "EXCLUDED"])
async def test_review_cannot_enter_hot_or_notifications_through_legacy_scores(session_factory, assortment_status):
    class Analyzer:
        async def analyze(self, _context):
            return LeadAnalysis(is_lead=True, lead_score=90, intent=Intent.PRICE,
                                product_category="CHAIRS", language="ru", reason="Price")
    signal = await ContactService(session_factory).persist_signal(make_post(), make_comment())
    await LeadService(session_factory, Analyzer(), 50).process_signal(signal)
    async with session_factory() as session:
        lead = await session.scalar(select(Lead))
        lead.status, lead.lead_score = LeadStatus.NEW, 90
        lead.analysis_details = {"intelligence_version": "2.0", "is_commercial": False,
                                 "assortment": {"status": assortment_status}}
        await session.commit()
        eligible = await session.scalar(select(Lead.id).join(Competitor).where(
            eligible_policy_clause(NotificationPolicy.HOT_ONLY, 50),
        ))
        assert eligible is None
    hot = _hot(session_factory)
    hot.hot_threshold = 50
    assert await hot.queue_count() == 0
    assert await hot.detail(lead.id) is None
    queries = WebQueryService(session_factory, hot_threshold=50)
    assert (await queries.signal_overview())["hot"] == 0
    assert (await queries.dashboard())["counts"]["hot"] == 0
    assert await queries.leads(quality="hot") == []
    assert await queries.signals(kind="hot") == []
    grouped = await queries.radar_posts_page()
    assert grouped.comment_count == 1 and sum(company.hot for company in grouped.companies) == 0
    workflow = LeadWorkflowService(session_factory, 50)
    assert await workflow.list_hot_leads() == []
    assert (await workflow.get_stats()).hot_leads == 0
    await AudienceEngine(session_factory, hot_threshold=50).recalculate_contact(signal.contact_id)


async def test_finished_furniture_repair_removes_an_unsupported_raw_material_guess(session_factory):
    signal = await ContactService(session_factory).persist_signal(
        make_post().model_copy(update={"caption": "Новая коллекция мебели"}), make_comment(),
    )
    async with session_factory() as session:
        lead = Lead(comment_id=signal.comment_id, contact_id=signal.contact_id,
                    competitor_id=signal.competitor_id, vertical=Vertical.FURNITURE,
                    status=LeadStatus.NEW, intent="PRICE", product_category="RAW_RATTAN",
                    lead_score=90, language="ru", analysis_details={})
        session.add(lead)
        await session.commit()
    service = LeadService(session_factory, RuleBasedLeadAnalyzer(), 70)
    await service.repair_assortment(dry_run=False)
    async with session_factory() as session:
        saved = await session.get(Lead, lead.id)
        assert saved.product_category is None
        assert saved.analysis_details["assortment"]["status"] == "REVIEW"
        assert saved.lead_score == 60
    assert (await service.repair_assortment())["updated"] == []
