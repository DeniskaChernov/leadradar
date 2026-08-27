"""
competitor_opportunity_service.py — V6 Competitor Intelligence V3 & Opportunity Engine.

Calculates Commercial Content Score per post/Reel and discovers market opportunities:
  - Commercial intent rate per 100 comments
  - Catalog demand gap discovery
  - Unanswered commercial demand opportunities
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ContentCommercialScore:
    post_id: str
    total_comments: int
    commercial_comments: int
    commercial_intent_rate: float  # per 100 comments
    price_intent_count: int
    availability_intent_count: int
    delivery_intent_count: int
    b2b_intent_count: int
    is_high_converting: bool


@dataclass(frozen=True, slots=True)
class CompetitorOpportunity:
    opportunity_type: str  # DEMAND_GAP, UNANSWERED_DEMAND, B2B_BULK, PRICE_SENSITIVE
    title: str
    description: str
    evidence_count: int
    suggested_action: str
    target_category: str | None


class CompetitorOpportunityEngine:
    """Discovers commercial opportunities from competitor interaction signals."""

    @classmethod
    def score_post_content(
        cls,
        *,
        post_id: str,
        total_comments: int,
        price_count: int = 0,
        availability_count: int = 0,
        delivery_count: int = 0,
        b2b_count: int = 0,
    ) -> ContentCommercialScore:
        commercial_comments = price_count + availability_count + delivery_count + b2b_count
        rate = (
            round((commercial_comments / total_comments) * 100, 2)
            if total_comments > 0
            else 0.0
        )
        is_high = rate >= 30.0 or b2b_count >= 3 or commercial_comments >= 10

        return ContentCommercialScore(
            post_id=post_id,
            total_comments=total_comments,
            commercial_comments=commercial_comments,
            commercial_intent_rate=rate,
            price_intent_count=price_count,
            availability_intent_count=availability_count,
            delivery_intent_count=delivery_count,
            b2b_intent_count=b2b_count,
            is_high_converting=is_high,
        )

    @classmethod
    def discover_opportunities(
        cls,
        *,
        competitor_name: str,
        unanswered_price_count: int = 0,
        unanswered_b2b_count: int = 0,
        top_requested_category: str | None = None,
    ) -> list[CompetitorOpportunity]:
        opportunities: list[CompetitorOpportunity] = []

        if unanswered_b2b_count >= 2:
            opportunities.append(
                CompetitorOpportunity(
                    opportunity_type="B2B_BULK",
                    title=f"Неотвеченный B2B-спрос у {competitor_name}",
                    description=f"Обнаружено {unanswered_b2b_count} оптовых запросов без открытого ответа.",
                    evidence_count=unanswered_b2b_count,
                    suggested_action="Связаться с потенциальными B2B-покупателями и предложить наш складской оптовый ассортимент.",
                    target_category=top_requested_category or "CHAIRS",
                )
            )

        if unanswered_price_count >= 5:
            opportunities.append(
                CompetitorOpportunity(
                    opportunity_type="UNANSWERED_DEMAND",
                    title=f"Массовые вопросы по ценам у {competitor_name}",
                    description=f"{unanswered_price_count} пользователей не получили открытого ответа по цене.",
                    evidence_count=unanswered_price_count,
                    suggested_action="Запустить таргетированную рекламу с открытой выгодной ценой на аналог товара.",
                    target_category=top_requested_category or "DINING_SET",
                )
            )

        if top_requested_category:
            opportunities.append(
                CompetitorOpportunity(
                    opportunity_type="DEMAND_GAP",
                    title=f"Высокий спрос на категорию {top_requested_category}",
                    description=f"Категория {top_requested_category} является лидером по коммерческим вопросам у {competitor_name}.",
                    evidence_count=unanswered_price_count + unanswered_b2b_count + 1,
                    suggested_action=f"Увеличить продвижение товаров из категории {top_requested_category}.",
                    target_category=top_requested_category,
                )
            )

        return opportunities
