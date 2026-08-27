"""
google_marketing_service.py — V6 Google Marketing Intelligence (GA4, Search Console, Google Ads).

Aggregates observed search terms, landing page traffic, and campaign performance:
  - Google Ads Search Terms performance (clicks, spend, CPL, ROI)
  - Search Console query CTR & position tracking
  - GA4 traffic source conversions
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SearchTermMetric:
    search_term: str
    impressions: int
    clicks: int
    spend_usd: float
    leads_count: int
    hot_count: int
    cost_per_lead: float
    is_high_performing: bool


@dataclass(frozen=True, slots=True)
class SearchConsoleInsight:
    query: str
    clicks: int
    impressions: int
    ctr_percent: float
    average_position: float


class GoogleMarketingEngine:
    """Aggregates and analyzes Google Ads search terms and Search Console queries."""

    @classmethod
    def analyze_search_terms(
        cls,
        terms_data: Sequence[dict[str, float | int | str]],
    ) -> list[SearchTermMetric]:
        metrics: list[SearchTermMetric] = []
        for item in terms_data:
            term = str(item.get("search_term") or "")
            imp = int(item.get("impressions") or 0)
            clicks = int(item.get("clicks") or 0)
            spend = float(item.get("spend_usd") or 0.0)
            leads = int(item.get("leads_count") or 0)
            hot = int(item.get("hot_count") or 0)

            cpl = round(spend / leads, 2) if leads > 0 else 0.0
            is_high = hot >= 2 or (leads >= 5 and cpl <= 15.0)

            metrics.append(
                SearchTermMetric(
                    search_term=term,
                    impressions=imp,
                    clicks=clicks,
                    spend_usd=round(spend, 2),
                    leads_count=leads,
                    hot_count=hot,
                    cost_per_lead=cpl,
                    is_high_performing=is_high,
                )
            )
        return metrics

    @classmethod
    def analyze_search_console_queries(
        cls,
        query_data: Sequence[dict[str, float | int | str]],
    ) -> list[SearchConsoleInsight]:
        insights: list[SearchConsoleInsight] = []
        for item in query_data:
            query = str(item.get("query") or "")
            clicks = int(item.get("clicks") or 0)
            imp = int(item.get("impressions") or 0)
            ctr = round((clicks / imp) * 100, 2) if imp > 0 else 0.0
            pos = round(float(item.get("average_position") or 0.0), 1)

            insights.append(
                SearchConsoleInsight(
                    query=query,
                    clicks=clicks,
                    impressions=imp,
                    ctr_percent=ctr,
                    average_position=pos,
                )
            )
        return insights
