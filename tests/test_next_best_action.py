from __future__ import annotations

from decimal import Decimal

from app.db.models import Product, Vertical
from app.services.next_best_action_service import NextBestActionEngine


def _product(*, stock: int | None = None) -> Product:
    return Product(
        id=7,
        canonical_key="confirmed-chair",
        sku=None,
        name="CORDA",
        vertical=Vertical.ARTIFICIAL_RATTAN,
        category="CHAIR",
        price=Decimal("33.00"),
        currency="USD",
        stock=stock,
        colors_json=[],
        b2b_suitability="BULK_CONFIRMED",
        active=True,
    )


def test_b2b_action_never_invents_wholesale_sku_discount_or_stock():
    recommendation = NextBestActionEngine.recommend(
        buyer_role="B2B_HORECA",
        intent="QUANTITY",
        product_category="CHAIRS",
        lead_score=90,
        quantity=50,
    )

    assert recommendation.action_type == "B2B_PROPOSAL"
    assert recommendation.recommended_sku is None
    assert "скидк" not in recommendation.description.casefold()
    assert "проверить по каталогу" in recommendation.description.casefold()


def test_confirmed_catalog_product_is_recommended_with_unknown_stock_warning():
    recommendation = NextBestActionEngine.recommend(
        buyer_role="B2C_CONSUMER",
        intent="PRICE",
        product_category="CHAIRS",
        lead_score=88,
        catalog_products=[_product()],
        evidence_ids=[41],
    )

    assert recommendation.recommended_product_id == 7
    assert recommendation.recommended_sku is None
    assert "CORDA" in recommendation.title
    assert "33.00 USD" in recommendation.description
    assert "Наличие не подтверждено" in recommendation.description
    assert recommendation.evidence_ids == [41]


def test_confirmed_stock_can_be_stated_without_delivery_or_discount_claim():
    recommendation = NextBestActionEngine.recommend(
        buyer_role="B2C_CONSUMER",
        intent="AVAILABILITY",
        product_category="CHAIRS",
        lead_score=75,
        catalog_products=[_product(stock=12)],
    )

    assert "Подтверждённый остаток: 12" in recommendation.description
    assert "доставк" not in recommendation.description.casefold()
    assert "скидк" not in recommendation.description.casefold()


def test_designer_action_requests_facts_instead_of_promising_assets():
    recommendation = NextBestActionEngine.recommend(
        buyer_role="DESIGNER_CONTRACTOR",
        intent="CATALOG",
        product_category="DINING_SET",
        lead_score=75,
    )

    assert recommendation.action_type == "QUESTION"
    assert recommendation.recommended_sku is None
    assert "не подтверждены" in recommendation.description
