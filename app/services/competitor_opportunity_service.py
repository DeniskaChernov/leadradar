"""
competitor_opportunity_service.py — V6 Competitor Intelligence V3 & Opportunity Engine.

Calculates an observed Commercial Content Score per post/Reel:
  - Commercial intent rate per 100 comments

Catalog coverage belongs to ProductCatalogService/WebQueryService. This module intentionally
does not infer competitor replies, stock, prices or advertising actions.
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


class CompetitorOpportunityEngine:
    """Scores only directly observed public interaction signals."""

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

