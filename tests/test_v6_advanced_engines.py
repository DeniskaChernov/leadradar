"""Offline tests for evidence decomposition and imported Google datasets."""

from __future__ import annotations

from app.services.evidence_bundle_service import EvidenceBundleEngine
from app.services.google_marketing_service import GoogleMarketingEngine


def test_evidence_bundle_score_decomposition():
    score = EvidenceBundleEngine.decompose_lead_score(
        intent_score=90,
        activity_score=80,
        specificity_score=85,
        value_score=70,
        fit_score=95,
        confidence_score=90,
    )
    assert 0 <= score.priority_score <= 100
    assert score.priority_score >= 70
    assert "Приоритет" in score.explanation


def test_google_marketing_search_terms():
    data = [
        {"search_term": "мебель для ресторана оптом", "impressions": 1000, "clicks": 150, "spend_usd": 45.0, "leads_count": 9, "hot_count": 3},
        {"search_term": "дешевый стул", "impressions": 500, "clicks": 20, "spend_usd": 10.0, "leads_count": 0, "hot_count": 0},
    ]
    metrics = GoogleMarketingEngine.analyze_search_terms(data)
    assert len(metrics) == 2
    assert metrics[0].is_high_performing is True
    assert metrics[0].cost_per_lead == 5.0
    assert metrics[1].is_high_performing is False


def test_google_marketing_search_console():
    data = [
        {"query": "ротанг узбекистан", "clicks": 120, "impressions": 1200, "average_position": 2.1},
    ]
    insights = GoogleMarketingEngine.analyze_search_console_queries(data)
    assert len(insights) == 1
    assert insights[0].ctr_percent == 10.0
    assert insights[0].average_position == 2.1
