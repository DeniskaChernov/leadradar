"""
test_unit_economics.py — Tests for V6 Unit Economics Engine.
"""

from __future__ import annotations

from app.services.unit_economics_service import UnitEconomicsEngine


def test_calculate_source_economics_valid():
    econ = UnitEconomicsEngine.calculate_source_economics(
        source_name="AIKO Instagram Comments",
        total_spend=50.0,
        signals_count=500,
        leads_count=100,
        hot_count=25,
        won_count=5,
        total_revenue=1250.0,
    )
    assert econ.source_name == "AIKO Instagram Comments"
    assert econ.cost_per_signal == 0.10
    assert econ.cost_per_lead == 0.50
    assert econ.cost_per_hot == 2.00
    assert econ.cost_per_won == 10.00
    assert econ.roi_ratio == 25.0  # 1250 / 50


def test_calculate_source_economics_zero_division_safe():
    econ = UnitEconomicsEngine.calculate_source_economics(
        source_name="Zero Activity Source",
        total_spend=0.0,
        signals_count=0,
        leads_count=0,
        hot_count=0,
        won_count=0,
        total_revenue=0.0,
    )
    assert econ.cost_per_signal == 0.0
    assert econ.cost_per_lead == 0.0
    assert econ.cost_per_hot == 0.0
    assert econ.cost_per_won == 0.0
    assert econ.roi_ratio == 0.0
