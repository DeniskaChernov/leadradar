from datetime import UTC, datetime, timedelta

from app.schemas.leads import BuyerRole, CommercialSignalQuality, Intent
from app.services.ai_service import LeadAnalysisContext, RuleBasedLeadAnalyzer
from app.services.b2b_policy import B2BPolicy
from app.services.lead_scoring_v3 import HistoricalSignal, LeadScorerV3


def _history(
    intent: Intent,
    *,
    days_ago: int = 0,
    competitor: str = "competitor-a",
) -> HistoricalSignal:
    return HistoricalSignal(
        competitor=competitor,
        intent=intent,
        quality=CommercialSignalQuality.MEDIUM_COMMERCIAL,
        observed_at=datetime.now(UTC) - timedelta(days=days_ago),
    )


def _score(history: list[HistoricalSignal], intent: Intent = Intent.PRICE):
    return LeadScorerV3.score(
        is_lead=True,
        intent=intent,
        legacy_intent_score=86,
        text="Какая цена?",
        product="DINING_SET",
        evidence_ids=[1],
        history=history,
        current_competitor="competitor-b",
        urgency_score=60,
    )


def test_absent_validated_history_does_not_boost_multi_competitor_activity():
    context = LeadAnalysisContext(
        competitor="competitor-c",
        post_caption="Обеденный стол",
        comment="Какая цена?",
        username="buyer",
        previous_signals=[],
        previous_interests=[],
        evidence_ids=[1],
    )

    result = RuleBasedLeadAnalyzer().classify(context)

    assert result is not None
    assert result.factors["history_boost"] == 0
    assert result.factors["validated_commercial_count"] == 0
    assert result.factors["validated_competitor_count"] == 1


def test_progressive_intent_sequence_is_stronger_than_repetition():
    progression = _score([_history(Intent.PRICE), _history(Intent.AVAILABILITY)], Intent.DELIVERY)
    repetition = _score([_history(Intent.PRICE), _history(Intent.PRICE)], Intent.PRICE)

    assert progression.sequence_score > repetition.sequence_score
    assert progression.activity_score > repetition.activity_score
    assert progression.priority_score > repetition.priority_score


def test_signal_half_life_is_used_in_history_score():
    fresh = _score([_history(Intent.PRICE, days_ago=0)])
    old = _score([_history(Intent.PRICE, days_ago=56)])

    assert fresh.history_boost > old.history_boost
    assert fresh.activity_score > old.activity_score


def test_repeated_price_signals_have_diminishing_returns_and_cap():
    repeated = _score([_history(Intent.PRICE) for _ in range(20)])

    assert repeated.history_boost <= 15
    assert repeated.sequence_score == 0
    assert repeated.activity_score <= 100


def test_b2b_policy_requires_context_or_meaningful_quantity():
    assert B2BPolicy.assess("10 стульев домой").role == BuyerRole.B2C_CONSUMER
    assert B2BPolicy.assess("20 стульев").role == BuyerRole.B2C_CONSUMER
    assert B2BPolicy.assess("30 стульев").role == BuyerRole.B2B_HORECA
    assert B2BPolicy.assess("10 стульев для ресторана").role == BuyerRole.B2B_HORECA
    assert B2BPolicy.assess("50 стульев").tier == "STRONG"


def test_missing_evidence_reduces_confidence_without_changing_facts():
    with_evidence = LeadScorerV3.score(
        is_lead=True,
        intent=Intent.BUY,
        legacy_intent_score=94,
        text="Хочу заказать стол",
        product="TABLE",
        evidence_ids=[10],
        history=[],
        current_competitor="aiko",
        urgency_score=60,
    )
    without_evidence = LeadScorerV3.score(
        is_lead=True,
        intent=Intent.BUY,
        legacy_intent_score=94,
        text="Хочу заказать стол",
        product="TABLE",
        evidence_ids=[],
        history=[],
        current_competitor="aiko",
        urgency_score=60,
    )

    assert with_evidence.confidence_score > without_evidence.confidence_score
    assert with_evidence.priority_score == without_evidence.priority_score


def test_rule_analysis_exposes_complete_v3_decision_contract():
    result = RuleBasedLeadAnalyzer().classify(
        LeadAnalysisContext(
            competitor="aiko",
            post_caption="Обеденный комплект",
            comment="Нужна доставка, хочу заказать 6 стульев",
            username="buyer",
            previous_signals=[],
            previous_interests=[],
            evidence_ids=[3],
        )
    )

    assert result is not None
    assert result.intelligence_version == "3.0"
    assert result.is_commercial is True
    assert result.priority_score == result.lead_score
    assert result.intent_score > 0
    assert result.activity_score > 0
    assert result.specificity_score > 0
    assert result.value_score > 0
    assert result.fit_score > 0
    assert result.confidence_score > 0
    assert result.evidence_ids == [3]
    assert result.next_best_action
    assert result.short_reason


def _classify(comment: str, *, caption: str = "Мебель для бизнеса"):
    result = RuleBasedLeadAnalyzer().classify(
        LeadAnalysisContext(
            competitor="competitor",
            post_caption=caption,
            comment=comment,
            username="buyer",
            previous_signals=[],
            previous_interests=[],
            evidence_ids=[101],
        )
    )
    assert result is not None
    return result


def test_buyer_role_does_not_overwrite_specific_commercial_intent():
    b2b_price = _classify("Для ресторана сколько стоит этот комплект?")
    b2b_delivery = _classify("Для кафе нужна доставка сегодня")
    designer_catalog = _classify("Я дизайнер, пришлите каталог для проекта")

    assert (b2b_price.intent, b2b_price.buyer_role) == (
        Intent.PRICE,
        BuyerRole.B2B_HORECA,
    )
    assert (b2b_delivery.intent, b2b_delivery.buyer_role) == (
        Intent.DELIVERY,
        BuyerRole.B2B_HORECA,
    )
    assert (designer_catalog.intent, designer_catalog.buyer_role) == (
        Intent.CATALOG,
        BuyerRole.DESIGNER_CONTRACTOR,
    )
    assert "цен" in b2b_price.recommended_action.casefold()
    assert "достав" in b2b_delivery.recommended_action.casefold()
    assert "подборк" in designer_catalog.recommended_action.casefold()


def test_role_only_signal_keeps_safe_buy_fallback():
    result = _classify("Мебель для летней террасы кафе")

    assert result.is_lead is True
    assert result.intent == Intent.BUY
    assert result.buyer_role == BuyerRole.B2B_HORECA
    assert any("B2B" in item for item in result.evidence)


def test_price_objection_is_visible_and_reduces_priority():
    neutral = _classify("Какая цена этого стола?", caption="Стол")
    objection = _classify("Цена этого стола слишком дорогая", caption="Стол")

    assert objection.intent == Intent.PRICE
    assert objection.is_lead is True
    assert objection.priority_score == objection.lead_score
    assert objection.priority_score < neutral.priority_score
    assert objection.factors["objection_penalty"] == 8
    assert "Ценовое возражение" in objection.risk_flags
    assert "скидк" in objection.recommended_action.casefold()
