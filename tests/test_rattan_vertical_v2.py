from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import func, select

from app.db.models import (
    AudienceMembership,
    AudienceSegment,
    BusinessEntity,
    Competitor,
    Evidence,
    Lead,
    PublicSignal,
    Vertical,
)
from app.services.ai_service import RuleBasedLeadAnalyzer
from app.services.audience_service import AudienceEngine
from app.services.contact_service import ContactService
from app.services.lead_service import LeadService
from app.services.rattan_taxonomy_service import RattanTaxonomyService
from app.services.rattan_vertical_service import RattanVerticalService
from app.web.queries import WebQueryService
from tests.test_contact_service import make_comment, make_post


def test_rattan_vertical_v2_golden_taxonomy():
    rows = json.loads(
        Path("fixtures/rattan_vertical_v2_golden.json").read_text(encoding="utf-8")
    )
    for row in rows:
        result = RattanTaxonomyService.classify(row["text"])
        assert result.is_rattan is row["is_rattan"], row["text"]
        assert result.layer.value == row["layer"], row["text"]
        if row.get("product"):
            assert row["product"] in result.products, row["text"]
        if row.get("profile"):
            assert row["profile"] in result.material_profiles, row["text"]
        if row.get("role"):
            assert result.role.value == row["role"], row["text"]


async def test_vertical_propagates_to_signal_evidence_lead_competitor_and_business(
    session_factory,
):
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

    async with session_factory() as session:
        public_signal = await session.get(PublicSignal, signal.public_signal_id)
        evidence = await session.scalar(
            select(Evidence).where(Evidence.public_signal_id == public_signal.id)
        )
        lead = await session.scalar(select(Lead).where(Lead.comment_id == signal.comment_id))
        competitor = await session.get(Competitor, signal.competitor_id)
        business = await session.get(BusinessEntity, competitor.business_id)

    assert signal.vertical == Vertical.ARTIFICIAL_RATTAN
    assert public_signal.vertical == Vertical.ARTIFICIAL_RATTAN
    assert evidence.vertical == Vertical.ARTIFICIAL_RATTAN
    assert lead.vertical == Vertical.ARTIFICIAL_RATTAN
    assert lead.product_category in {"RAW_RATTAN", "COIL", "KG_PRICE"}
    assert competitor.vertical == Vertical.ARTIFICIAL_RATTAN
    assert Vertical.ARTIFICIAL_RATTAN.value in business.verticals_json
    assert evidence.raw_data["rattan_taxonomy"]["layer"] == "RAW_MATERIAL"


async def test_plain_table_stays_furniture_and_never_enters_rattan_segment(session_factory):
    signal = await ContactService(session_factory).persist_signal(
        make_post().model_copy(update={"caption": "Кухонный стол из массива"}),
        make_comment("plain-table-v2").model_copy(
            update={"platform_comment_id": "plain-table-v2", "text": "стол цена?"}
        ),
    )
    engine = AudienceEngine(session_factory, 70)
    await LeadService(
        session_factory,
        RuleBasedLeadAnalyzer(),
        hot_threshold=70,
        audience_engine=engine,
    ).process_signal(signal)
    await engine.recalculate_contact(signal.contact_id)

    async with session_factory() as session:
        lead = await session.scalar(select(Lead).where(Lead.comment_id == signal.comment_id))
        membership = await session.scalar(
            select(AudienceMembership)
            .join(AudienceSegment, AudienceSegment.id == AudienceMembership.segment_id)
            .where(
                AudienceMembership.contact_id == signal.contact_id,
                AudienceSegment.slug == "rattan",
            )
        )
    assert lead.vertical == Vertical.FURNITURE
    assert membership is not None and membership.active is False


async def test_generic_rattan_context_does_not_fake_raw_material_interest(
    session_factory,
):
    signal = await ContactService(session_factory).persist_signal(
        make_post().model_copy(update={"caption": "Rattan inspiration"}),
        make_comment("generic-rattan-v2").model_copy(
            update={
                "platform_comment_id": "generic-rattan-v2",
                "text": "Красиво",
            }
        ),
    )

    stats = await RattanVerticalService(session_factory).rebuild()
    async with session_factory() as session:
        evidence = await session.scalar(
            select(Evidence).where(Evidence.public_signal_id == signal.public_signal_id)
        )

    assert signal.vertical == Vertical.ARTIFICIAL_RATTAN
    assert evidence is not None
    assert evidence.topic is None
    assert evidence.intent is None
    assert evidence.raw_data["rattan_taxonomy"]["layer"] == "NONE"
    assert stats.rattan_signals == 1
    assert stats.raw_material_signals == 0
    assert stats.unclassified_rattan_signals == 1


async def test_rattan_rebuild_and_workspace_are_idempotent(session_factory):
    contact_service = ContactService(session_factory)
    await contact_service.persist_signal(
        make_post().model_copy(update={"caption": "Rattan sofa outdoor"}),
        make_comment("rattan-workspace-v2").model_copy(
            update={"platform_comment_id": "rattan-workspace-v2", "text": "narxi?"}
        ),
    )
    service = RattanVerticalService(session_factory)
    first = await service.rebuild()
    second = await service.rebuild()
    async with session_factory() as session:
        signal_count = await session.scalar(select(func.count(PublicSignal.id)))
        evidence_count = await session.scalar(select(func.count(Evidence.id)))
    workspace = await WebQueryService(session_factory, hot_threshold=70).rattan_workspace()

    assert first == second
    assert signal_count == 1
    assert evidence_count == 1
    assert workspace["rattan_counts"]["companies"] == 1
