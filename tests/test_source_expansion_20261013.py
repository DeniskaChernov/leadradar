from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from app.db.models import Competitor, ContactEvent, CoverageStatus, Lead, LeadStatus, Post
from app.schemas.leads import Intent
from app.services.ai_service import HybridLeadAnalyzer, LeadAnalysisContext, RuleBasedLeadAnalyzer
from app.services.contact_service import ContactService
from app.services.lead_service import LeadService
from app.services.market_intelligence_service import MarketIntelligenceService
from app.services.radar_results_service import RadarPostGroup
from tests.test_contact_service import make_comment, make_post


def context(comment):
    return LeadAnalysisContext(
        competitor="furniture.uz", post_caption="Столы и стулья для дома и кафе",
        comment=comment, username="buyer", previous_signals=[], previous_interests=[],
        source_vertical="FURNITURE",
    )


@pytest.mark.parametrize("comment", [
    "БАРАКА ТОПИНГ, НАРХЛАРИНИ ЕЗИБ КОЛДИРГАНИНГИЗ УЧУН",
    "Нархларини ёзиб қолдирганингиз учун раҳмат",
    "Narxlarni yozib qoldirganingiz uchun rahmat",
    "Narxlarni yozib qo'yganingiz uchun raxmat",
    "Спасибо, что указали цены!",
    "Спасибо за прайс",
    "Благодарю за цены на стулья",
    "Цены опубликовали, спасибо!",
])
def test_price_acknowledgement_is_not_a_buying_request(comment):
    result = RuleBasedLeadAnalyzer().classify(context(comment))
    assert result is not None
    assert result.is_lead is False
    assert result.intent == Intent.REACTION
    assert result.lead_score < 70


@pytest.mark.parametrize("comment", [
    "Раҳмат, нархи қанча?",
    "Спасибо за прайс. Можно доставку?",
    "Baraka toping narxini ayting",
    "Спасибо, сколько стоит плетёный стул",
    "Narxlarni yozib qoldiring rahmat",
    "Раҳмат нархини ёзинг",
    "Спасибо за цены, хочу заказать 2 стула",
    "Спасибо за прайс, нужна мебель для кафе",
    "Спасибо за прайс, пришлите адрес",
    "Спасибо за цены, доставку можно",
    "Раҳмат нархларини ёзиб қолдирганингиз учун, каталог юборинг",
    "Цена",
    "narx",
])
def test_gratitude_does_not_hide_a_new_request(comment):
    rules = RuleBasedLeadAnalyzer()
    assert not rules.is_price_acknowledgement(comment)
    result = rules.classify(context(comment))
    assert result is not None and result.is_lead


@pytest.mark.parametrize("mode", ["rules", "hybrid", "openai"])
async def test_acknowledgement_never_spends_openai_credits(mode):
    class ForbiddenAI:
        async def analyze(self, context):
            raise AssertionError("Acknowledgement must stay local")

    analyzer = HybridLeadAnalyzer(RuleBasedLeadAnalyzer(), ForbiddenAI(), mode=mode)
    result, source = await analyzer.analyze_with_source(context("Спасибо за прайс"))
    assert source == "local_rules" and not result.is_lead


async def test_selected_activation_dry_run_and_retry_are_idempotent(session_factory):
    service = MarketIntelligenceService(session_factory)
    await service.sync_catalog()
    chosen = ("@rona_rattan.uz", "https://www.instagram.com/komandor_uz/")
    preview = await service.activate_portfolio(handles=chosen, dry_run=True)
    assert set(preview["handles"]) == {"rona_rattan.uz", "komandor_uz"}
    async with session_factory() as session:
        before = set(await session.scalars(select(Competitor.normalized_handle).where(Competitor.active)))
    assert "komandor_uz" not in before and "rona_rattan.uz" not in before
    applied = await service.activate_portfolio(handles=chosen)
    retry = await service.activate_portfolio(handles=chosen)
    assert applied["activated"] == 2
    assert retry["activated"] == 0 and retry["already_active"] == 2
    async with session_factory() as session:
        after = set(await session.scalars(select(Competitor.normalized_handle).where(Competitor.active)))
    assert after == before | {"rona_rattan.uz", "komandor_uz"}


@pytest.mark.parametrize("handles", [(), ("",), ("rona_rattan.uz", "missing.uz")])
async def test_invalid_selected_sources_do_not_partially_activate(session_factory, handles):
    service = MarketIntelligenceService(session_factory)
    await service.sync_catalog()
    with pytest.raises(ValueError):
        await service.activate_portfolio(handles=handles)
    async with session_factory() as session:
        rona = await session.scalar(select(Competitor).where(Competitor.normalized_handle == "rona_rattan.uz"))
    assert not rona.active


def test_parent_comment_coverage_does_not_claim_replies():
    post = Post(
        id=1, platform_post_id="public-post", competitor_id=1,
        url="https://www.instagram.com/p/public-post/", caption="Мебель",
        comments_count=2, last_synced_remote_count=2,
        coverage_status=CoverageStatus.FULL, comments_checked_at=datetime.now(UTC),
        last_comment_provider="scrapecreators",
    )
    group = RadarPostGroup(post, total=2, leads=1, hot=1, pending=0, rejected=1)
    assert group.coverage == "FULL"
    assert group.replies_excluded
    post.last_comment_provider = "brightdata"
    assert not group.replies_excluded


async def test_saved_acknowledgement_repair_is_local_and_idempotent(session_factory):
    class ForbiddenAnalyzer:
        async def analyze(self, context):
            raise AssertionError("Repair must never invoke an external analyzer")

    service = LeadService(session_factory, ForbiddenAnalyzer(), hot_threshold=70)
    ids = []
    for index in range(2):
        comment = make_comment(f"ack-{index}").model_copy(update={"text": "Спасибо за прайс"})
        signal = await ContactService(session_factory).persist_signal(make_post(), comment)
        shell = await service.ensure_analyzing(signal)
        ids.append(shell.lead_id)
    async with session_factory() as session:
        for lead_id in ids:
            lead = await session.get(Lead, lead_id)
            lead.status = LeadStatus.NEW
            lead.lead_score = 78
            lead.intent = "PRICE"
        managed = await session.get(Lead, ids[1])
        managed.status = LeadStatus.TAKEN
        managed.assigned_manager_telegram_id = 1001
        await session.commit()
        before = await session.scalar(select(func.count(ContactEvent.id)))
    preview = await service.repair_price_acknowledgements()
    assert preview == {"dry_run": True, "matched": [ids[0]], "repaired": []}
    async with session_factory() as session:
        assert (await session.get(Lead, ids[0])).status == LeadStatus.NEW
    first = await service.repair_price_acknowledgements(dry_run=False)
    retry = await service.repair_price_acknowledgements(dry_run=False)
    assert first["repaired"] == [ids[0]] and retry["matched"] == []
    async with session_factory() as session:
        repaired = await session.get(Lead, ids[0])
        managed = await session.get(Lead, ids[1])
        assert repaired.status == LeadStatus.NOT_LEAD and repaired.lead_score < 70
        assert repaired.analysis_details["qualification_guard"] == "price_acknowledgement:v1"
        assert managed.status == LeadStatus.TAKEN and managed.lead_score == 78
        assert managed.assigned_manager_telegram_id == 1001
        assert await session.scalar(select(func.count(ContactEvent.id))) == before + 1


async def test_selected_activation_rejects_non_instagram_source(session_factory):
    service = MarketIntelligenceService(session_factory)
    await service.sync_catalog()
    async with session_factory() as session:
        row = await session.scalar(select(Competitor).where(Competitor.normalized_handle == "komandor_uz"))
        row.platform = "telegram"
        await session.commit()
    with pytest.raises(ValueError):
        await service.activate_portfolio(handles=("rona_rattan.uz", "komandor_uz"))
    async with session_factory() as session:
        row = await session.scalar(select(Competitor).where(Competitor.normalized_handle == "rona_rattan.uz"))
        assert not row.active
