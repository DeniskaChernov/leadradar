from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select

from app.db.models import Competitor, Lead, Vertical
from app.services.ai_service import RuleBasedLeadAnalyzer
from app.services.audience_service import AudienceEngine
from app.services.contact_service import ContactService
from app.services.lead_service import LeadService
from app.services.rattan_taxonomy_service import RattanTaxonomyService
from app.services.rattan_vertical_service import RattanVerticalService
from app.web.queries import WebQueryService
from tests.test_contact_service import make_comment, make_post


def test_rattan_vertical_v2_golden_taxonomy():
    rows = json.loads(Path("fixtures/rattan_vertical_v2_golden.json").read_text(encoding="utf-8"))
    for row in rows:
        result = RattanTaxonomyService.classify(row["text"])
        assert result.is_rattan is row["is_rattan"], row["text"]
        assert result.layer.value == row["layer"], row["text"]


async def test_rebuild_classifies_signal_but_does_not_auto_enroll_source(session_factory):
    post = make_post().model_copy(
        update={"caption": "Искусственный ротанг в бухтах, профиль 8 мм полукруг"}
    )
    comment = make_comment("rattan-v2-raw").model_copy(
        update={
            "platform_comment_id": "rattan-v2-raw",
            "text": "Нужен ротанг 50 кг, цена за кг?",
        }
    )
    signal = await ContactService(session_factory).persist_signal(post, comment)
    await LeadService(
        session_factory,
        RuleBasedLeadAnalyzer(),
        hot_threshold=70,
        audience_engine=AudienceEngine(session_factory, 70),
    ).process_signal(signal)
    stats = await RattanVerticalService(session_factory).rebuild()
    workspace = await WebQueryService(session_factory, hot_threshold=70).rattan_workspace()

    async with session_factory() as session:
        competitor = await session.get(Competitor, signal.competitor_id)
        lead = await session.scalar(select(Lead).where(Lead.comment_id == signal.comment_id))

    assert lead is not None
    assert lead.vertical == Vertical.ARTIFICIAL_RATTAN
    assert competitor is not None
    assert competitor.vertical == Vertical.FURNITURE
    assert stats.enrolled_competitors == 0
    assert stats.orphan_rattan_signals >= 1
    assert workspace["rattan_counts"]["portfolio_empty"] is True
    assert workspace["rattan_counts"]["companies"] == 0
    assert workspace["rattan_counts"]["signals"] == 0


async def test_explicit_enrollment_opens_rattan_portfolio(session_factory):
    post = make_post().model_copy(update={"caption": "Искусственный ротанг мебель"})
    comment = make_comment("rattan-enrolled").model_copy(
        update={
            "platform_comment_id": "rattan-enrolled",
            "text": "Сколько стоит комплект из ротанга?",
        }
    )
    signal = await ContactService(session_factory).persist_signal(post, comment)
    await LeadService(
        session_factory,
        RuleBasedLeadAnalyzer(),
        hot_threshold=70,
        audience_engine=AudienceEngine(session_factory, 70),
    ).process_signal(signal)
    service = RattanVerticalService(session_factory)
    await service.rebuild()
    await service.enroll_competitor(signal.competitor_id, vertical=Vertical.ARTIFICIAL_RATTAN)
    workspace = await WebQueryService(session_factory, hot_threshold=70).rattan_workspace()

    assert workspace["rattan_counts"]["portfolio_empty"] is False
    assert workspace["rattan_counts"]["companies"] == 1
    assert workspace["rattan_companies"][0].id == signal.competitor_id
    assert workspace["rattan_counts"]["signals"] >= 1


async def test_crm_vertical_setting_enrolls_portfolio(session_factory):
    from app.services.crm_service import CRMService

    post = make_post().model_copy(update={"caption": "Искусственный ротанг"})
    comment = make_comment("rattan-crm-enroll").model_copy(
        update={
            "platform_comment_id": "rattan-crm-enroll",
            "text": "Нужен ротанг оптом, цена?",
        }
    )
    signal = await ContactService(session_factory).persist_signal(post, comment)
    await LeadService(
        session_factory,
        RuleBasedLeadAnalyzer(),
        hot_threshold=70,
        audience_engine=AudienceEngine(session_factory, 70),
    ).process_signal(signal)
    await RattanVerticalService(session_factory).rebuild()
    await CRMService(session_factory).update_competitor(
        signal.competitor_id,
        vertical=Vertical.ARTIFICIAL_RATTAN.value,
    )
    workspace = await WebQueryService(session_factory, hot_threshold=70).rattan_workspace()
    assert workspace["rattan_counts"]["portfolio_empty"] is False
    assert workspace["rattan_counts"]["companies"] == 1
