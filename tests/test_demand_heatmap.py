"""
test_demand_heatmap.py — Tests for Phase 8 Demand Heatmap
"""

from __future__ import annotations

from sqlalchemy import select

from app.db.models import Competitor, Lead, LeadStatus
from app.schemas.leads import Intent
from app.services.contact_service import ContactService
from app.web.queries import WebQueryService
from tests.test_contact_service import make_comment, make_post


async def test_demand_heatmap_empty(session_factory):
    """Empty dataset returns zero total signals and valid 30-day series structure."""
    service = WebQueryService(session_factory, hot_threshold=70)
    hm = await service.demand_heatmap(days=30)

    assert hm["total_signals"] == 0
    assert hm["by_product"] == []
    assert hm["by_intent"] == []
    assert len(hm["days_series"]) == 30
    assert all(d["count"] == 0 for d in hm["days_series"])


async def test_demand_heatmap_with_signals(session_factory):
    """heatmap aggregates products, intents, and dates correctly."""
    sig = await ContactService(session_factory).persist_signal(
        make_post(), make_comment("c_hm_1")
    )
    async with session_factory() as session:
        comp = await session.scalar(
            select(Competitor).where(Competitor.normalized_handle == "aiko.uz")
        )
        assert comp is not None
        comp_id = comp.id

        lead = Lead(
            contact_id=sig.contact_id,
            competitor_id=comp_id,
            comment_id=sig.comment_id,
            lead_score=85,
            status=LeadStatus.NEW,
            intent=Intent.PRICE,
            product_category="RATTAN_SOFA",
        )
        session.add(lead)
        await session.commit()

    service = WebQueryService(session_factory, hot_threshold=70)
    hm = await service.demand_heatmap(competitor_id=comp_id, days=30)

    assert hm["total_signals"] >= 1
    assert ("RATTAN_SOFA", 1) in hm["by_product"]
    assert ("PRICE", 1) in hm["by_intent"]
    assert len(hm["days_series"]) == 30
    assert sum(d["count"] for d in hm["days_series"]) >= 1
