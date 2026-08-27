"""
test_demand_gap.py — Tests for Phase 7 Competitor Demand Gap Analytics
"""

from __future__ import annotations

from sqlalchemy import select

from app.db.models import Competitor, Lead, LeadStatus
from app.schemas.leads import Intent
from app.services.contact_service import ContactService
from app.web.queries import WebQueryService
from tests.test_contact_service import make_comment, make_post


async def test_demand_gap_score_empty(session_factory):
    """Empty competitor returns 0 total_commercial and valid boundary note."""
    async with session_factory() as session:
        comp = Competitor(
            handle="empty_comp",
            normalized_handle="empty_comp",
            display_name="Empty Comp",
            active=True,
        )
        session.add(comp)
        await session.commit()
        comp_id = comp.id

    service = WebQueryService(session_factory, hot_threshold=70)
    gap = await service.demand_gap_score(comp_id)

    assert gap["competitor_id"] == comp_id
    assert gap["total_commercial"] == 0
    assert gap["unanswered_count"] == 0
    assert gap["unanswered_rate"] == 0.0
    assert gap["b2b_gap"] == 0
    assert gap["multi_source_gap"] == 0
    assert "Direct" in gap["boundary_note"]


async def test_demand_gap_score_with_unanswered_leads(session_factory):
    """Calculates unanswered rate and B2B gap correctly."""
    cs = ContactService(session_factory)
    sig1 = await cs.persist_signal(make_post(), make_comment("c_gap_1"))
    sig2 = await cs.persist_signal(make_post(), make_comment("c_gap_2"))

    async with session_factory() as session:
        comp = await session.scalar(
            select(Competitor).where(Competitor.normalized_handle == "aiko.uz")
        )
        assert comp is not None
        comp_id = comp.id

        # Create 2 commercial leads for different comments: 1 NEW (unanswered B2B), 1 TAKEN (answered)
        l1 = Lead(
            contact_id=sig1.contact_id,
            competitor_id=comp_id,
            comment_id=sig1.comment_id,
            lead_score=85,
            status=LeadStatus.NEW,
            intent=Intent.BUY,
            product_category="HORECA",
            analysis_details={"buyer_role": "B2B_HORECA"},
        )
        l2 = Lead(
            contact_id=sig2.contact_id,
            competitor_id=comp_id,
            comment_id=sig2.comment_id,
            lead_score=75,
            status=LeadStatus.TAKEN,
            intent=Intent.PRICE,
            product_category="DINING_SET",
            analysis_details={"buyer_role": "B2C_CONSUMER"},
        )
        session.add_all([l1, l2])
        await session.commit()

    service = WebQueryService(session_factory, hot_threshold=70)
    gap = await service.demand_gap_score(comp_id)

    assert gap["total_commercial"] >= 2
    assert gap["unanswered_count"] >= 1
    assert gap["unanswered_rate"] > 0.0
    assert gap["b2b_gap"] >= 1


async def test_demand_gap_overview(session_factory):
    """Overview aggregates demand gap stats for all competitors."""
    async with session_factory() as session:
        comp = Competitor(
            handle="overview_comp",
            normalized_handle="overview_comp",
            display_name="Overview Comp",
            active=True,
        )
        session.add(comp)
        await session.commit()

    service = WebQueryService(session_factory, hot_threshold=70)
    overview = await service.demand_gap_overview()
    assert isinstance(overview, list)
    assert len(overview) >= 1
    assert "unanswered_rate" in overview[0]
    assert "b2b_gap" in overview[0]
