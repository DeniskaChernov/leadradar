"""
test_next_best_action.py — Tests for V6 Next Best Action Engine.
"""

from __future__ import annotations

from app.services.next_best_action_service import NextBestActionEngine


def test_recommend_b2b_proposal():
    rec = NextBestActionEngine.recommend(
        buyer_role="B2B_HORECA",
        intent="QUANTITY",
        product_category="CHAIRS",
        lead_score=90,
        quantity=50,
    )
    assert rec.action_type == "B2B_PROPOSAL"
    assert "B2B-предложение" in rec.title
    assert rec.urgency == "HIGH"


def test_recommend_multi_competitor_call():
    rec = NextBestActionEngine.recommend(
        buyer_role="B2C_CONSUMER",
        intent="PRICE",
        product_category="RATTAN_SOFA",
        lead_score=85,
        competitor_count=3,
    )
    assert rec.action_type == "CALL"
    assert "лид сравнивает конкурентов" in rec.title
    assert rec.urgency == "HIGH"


def test_recommend_designer_catalog():
    rec = NextBestActionEngine.recommend(
        buyer_role="DESIGNER_CONTRACTOR",
        intent="CATALOG",
        product_category="DINING_SET",
        lead_score=75,
    )
    assert rec.action_type == "OFFER"
    assert "3D-модели" in rec.title


def test_recommend_dining_set_offer():
    rec = NextBestActionEngine.recommend(
        buyer_role="B2C_CONSUMER",
        intent="PRICE",
        product_category="DINING_SET",
        lead_score=88,
    )
    assert rec.action_type == "OFFER"
    assert "на 6 персон" in rec.title
    assert rec.urgency == "HIGH"
