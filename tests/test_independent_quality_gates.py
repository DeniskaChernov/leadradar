from app.services.independent_quality_gates_service import IndependentQualityGatesService


def test_independent_quality_gates_are_deterministic_and_pass_unseen_sets():
    service = IndependentQualityGatesService()

    first = service.snapshot()
    second = service.snapshot()

    assert first.lead_unseen == second.lead_unseen
    assert first.rattan_unseen == second.rattan_unseen
    assert first.audience_unseen == second.audience_unseen
    assert first.lead_unseen.case_count >= 50
    assert first.rattan_unseen.case_count >= 30
    assert first.audience_unseen.labeled_decisions >= 100
    assert first.lead_unseen.passed
    assert first.rattan_unseen.passed
    assert first.audience_unseen.passed
    assert first.passed


def test_lead_unseen_reports_confusion_for_intent_mismatches():
    report = IndependentQualityGatesService().evaluate_lead_unseen()

    assert report.gate_id == "lead_unseen"
    assert report.intent_accuracy is not None
    assert report.f1 > 0
    assert isinstance(report.confusion, tuple)


def test_audience_unseen_evaluates_registry_segments_without_database():
    report = IndependentQualityGatesService().evaluate_audience_unseen()

    assert report.gate_id == "audience_unseen"
    assert report.case_count >= 30
    assert report.accuracy >= 0.90
