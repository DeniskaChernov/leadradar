from app.services.lead_intelligence_evaluation import LeadIntelligenceEvaluation


def test_lead_intelligence_v3_has_200_semantic_scenarios_and_quality_gate():
    report = LeadIntelligenceEvaluation().evaluate()

    assert report.scenario_count == 208
    assert report.passed, report
