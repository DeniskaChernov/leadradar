from app.schemas.leads import BuyerRole, Intent
from app.services.ai_service import LeadAnalysisContext, RuleBasedLeadAnalyzer
from app.services.lead_intelligence_challenge import LeadIntelligenceChallenge


def test_frozen_multilingual_challenge_is_deterministic_and_reports_gaps():
    evaluator = LeadIntelligenceChallenge()

    first = evaluator.evaluate()
    second = evaluator.evaluate()

    assert first == second
    assert first.dataset_version == "challenge:v1"
    assert first.scenario_count == 36
    assert {item.language: item.cases for item in first.language_scores} == {
        "ru": 12,
        "uz": 12,
        "uz-cyrl": 12,
    }
    assert first.passed is True
    assert first.lead_precision >= 0.90
    assert first.lead_recall >= 0.90
    assert first.hot_false_positive_rate == 0
    assert 0 < len(first.mismatches) <= 8
    assert first.intent_confusion


def test_challenge_fixes_negation_jobs_boundaries_and_latin_quantity():
    analyzer = RuleBasedLeadAnalyzer()

    def classify(comment: str):
        result = analyzer.classify(
            LeadAnalysisContext(
                competitor="challenge",
                post_caption="Мебель",
                comment=comment,
                username="buyer",
                previous_signals=[],
                previous_interests=[],
                evidence_ids=[1],
            )
        )
        assert result is not None
        return result

    negated = classify("Buyurtma qilmoqchi emasman")
    job = classify("Иш борми сизларда?")
    quantity = classify("35 ta stul kerak")
    collision = classify("Restoranga shu stolning narxi qancha?")

    assert (negated.is_lead, negated.intent) == (False, Intent.OTHER)
    assert (job.is_lead, job.buyer_role) == (False, BuyerRole.JOB_SEEKER)
    assert (quantity.intent, quantity.buyer_role, quantity.quantity) == (
        Intent.QUANTITY,
        BuyerRole.B2B_HORECA,
        35,
    )
    assert (collision.intent, collision.buyer_role) == (
        Intent.PRICE,
        BuyerRole.B2B_HORECA,
    )
