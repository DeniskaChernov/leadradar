"""
unit_economics_service.py — V6 Unit Economics & Cost Control Engine.

Calculates ROI and cost per acquisition metrics across lead generation sources:
  - cost_per_signal
  - cost_per_lead
  - cost_per_hot
  - cost_per_won
  - revenue_to_cost_ratio
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SourceEconomics:
    source_name: str
    total_spend: float  # USD
    signals_count: int
    leads_count: int
    hot_count: int
    won_count: int
    total_revenue: float  # USD
    cost_per_signal: float
    cost_per_lead: float
    cost_per_hot: float
    cost_per_won: float
    roi_ratio: float  # revenue / spend


class UnitEconomicsEngine:
    """Calculates deterministic unit economics metrics per data source / campaign."""

    @classmethod
    def calculate_source_economics(
        cls,
        *,
        source_name: str,
        total_spend: float,
        signals_count: int,
        leads_count: int,
        hot_count: int,
        won_count: int = 0,
        total_revenue: float = 0.0,
    ) -> SourceEconomics:
        cost_per_signal = round(total_spend / signals_count, 4) if signals_count > 0 else 0.0
        cost_per_lead = round(total_spend / leads_count, 2) if leads_count > 0 else 0.0
        cost_per_hot = round(total_spend / hot_count, 2) if hot_count > 0 else 0.0
        cost_per_won = round(total_spend / won_count, 2) if won_count > 0 else 0.0
        roi_ratio = round(total_revenue / total_spend, 2) if total_spend > 0 else 0.0

        return SourceEconomics(
            source_name=source_name,
            total_spend=round(total_spend, 2),
            signals_count=signals_count,
            leads_count=leads_count,
            hot_count=hot_count,
            won_count=won_count,
            total_revenue=round(total_revenue, 2),
            cost_per_signal=cost_per_signal,
            cost_per_lead=cost_per_lead,
            cost_per_hot=cost_per_hot,
            cost_per_won=cost_per_won,
            roi_ratio=roi_ratio,
        )
