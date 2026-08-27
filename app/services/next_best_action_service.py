"""
next_best_action_service.py — V6 Next Best Action Engine & Offer Recommendation.

Generates precise, evidence-backed next actions for managers based on:
  - Buyer role (B2B_HORECA vs DESIGNER_CONTRACTOR vs B2C_CONSUMER)
  - Intent (PRICE, AVAILABILITY, DELIVERY, QUANTITY, CATALOG)
  - Product category (DINING_SET, RATTAN_SOFA, CHAIRS, etc.)
  - Multi-competitor activity
  - Urgency & recency
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ActionRecommendation:
    action_type: str  # OFFER, CALL, QUESTION, B2B_PROPOSAL, FOLLOW_UP
    title: str
    description: str
    recommended_sku: str | None
    urgency: str  # HIGH, MEDIUM, LOW
    evidence_ids: Sequence[str]


class NextBestActionEngine:
    """Evidence-backed Next Best Action recommendation engine."""

    @classmethod
    def recommend(
        cls,
        *,
        buyer_role: str,
        intent: str,
        product_category: str | None,
        lead_score: int,
        competitor_count: int = 1,
        quantity: int | None = None,
        evidence_ids: Sequence[str] = (),
    ) -> ActionRecommendation:
        evidence_list = list(evidence_ids)

        # 1. High-volume B2B HoReCa orders
        if buyer_role == "B2B_HORECA" or (quantity and quantity >= 10):
            qty_str = f" на {quantity} единиц" if quantity else ""
            return ActionRecommendation(
                action_type="B2B_PROPOSAL",
                title=f"Сформировать B2B-предложение{qty_str}",
                description="Подготовить оптовый прайс-лист со скидкой за объём и согласовать сроки поставки.",
                recommended_sku="SKU-B2B-WHOLESALE",
                urgency="HIGH",
                evidence_ids=evidence_list,
            )

        # 2. Multi-competitor active shopping
        if competitor_count >= 2:
            return ActionRecommendation(
                action_type="CALL",
                title="Связаться сегодня: лид сравнивает конкурентов",
                description=f"Клиент замечен у {competitor_count} конкурентов. Подчеркнуть наличие на складе и быструю доставку.",
                recommended_sku=None,
                urgency="HIGH",
                evidence_ids=evidence_list,
            )

        # 3. Designers / Specifiers
        if buyer_role == "DESIGNER_CONTRACTOR":
            return ActionRecommendation(
                action_type="OFFER",
                title="Отправить 3D-модели и каталог для проекта",
                description="Предоставить файлы для визуализации и специальное агентское вознаграждение.",
                recommended_sku="SKU-DESIGNER-KIT",
                urgency="MEDIUM",
                evidence_ids=evidence_list,
            )

        # 4. Price & Availability inquiries on specific categories
        if intent in {"PRICE", "AVAILABILITY"} and product_category == "DINING_SET":
            return ActionRecommendation(
                action_type="OFFER",
                title="Предложить обеденный комплект на 6 персон в наличии",
                description="Показать обеденный стол + 6 плетёных стульев с фиксированной ценой и доставкой за 24 часа.",
                recommended_sku="SKU-DINING-SET-6P",
                urgency="HIGH" if lead_score >= 80 else "MEDIUM",
                evidence_ids=evidence_list,
            )

        # 5. Default follow-up
        return ActionRecommendation(
            action_type="FOLLOW_UP",
            title="Уточнить детали заказа и желаемые цвета",
            description="Связаться в мессенджере и предложить актуальные фото товара с нашего склада.",
            recommended_sku=None,
            urgency="MEDIUM" if lead_score >= 70 else "LOW",
            evidence_ids=evidence_list,
        )
