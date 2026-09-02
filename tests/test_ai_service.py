from types import SimpleNamespace

from app.schemas.leads import FunnelStage, Intent, LeadAnalysis, PurchaseHorizon, Urgency
from app.services.ai_service import LeadAnalysisContext, OpenAILeadAnalyzer, RuleBasedLeadAnalyzer


class FakeResponses:
    def __init__(self, result):
        self.result = result
        self.kwargs = None

    async def parse(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(output_parsed=self.result)


async def test_openai_structured_response_parsing():
    result = LeadAnalysis(
        is_lead=True,
        lead_score=91,
        intent=Intent.PRICE,
        product_category="DINING_SET",
        language="uz",
        reason="User asks for price",
    )
    responses = FakeResponses(result)
    client = SimpleNamespace(responses=responses)
    analyzer = OpenAILeadAnalyzer("unused", "configured-model", client=client)

    parsed = await analyzer.analyze(
        LeadAnalysisContext(
            competitor="aiko.uz",
            post_caption="price CTA",
            comment="narxi?",
            username="aziz",
            previous_signals=[],
            previous_interests=[],
        )
    )

    assert parsed.lead_score == 91
    assert responses.kwargs["model"] == "configured-model"
    assert responses.kwargs["text_format"] is LeadAnalysis
    assert responses.kwargs["store"] is False
    assert responses.kwargs["reasoning"] == {"effort": "low"}
    assert responses.kwargs["prompt_cache_key"] == "lead-radar-qualifier-v3"


async def test_openai_cannot_persist_unknown_evidence_ids():
    result = LeadAnalysis(
        is_lead=True,
        lead_score=88,
        intent=Intent.BUY,
        product_category="TABLE",
        language="ru",
        reason="Direct order request",
        confidence=92,
        confidence_score=92,
        evidence_ids=[7, 999],
    )
    analyzer = OpenAILeadAnalyzer(
        "unused",
        "configured-model",
        client=SimpleNamespace(responses=FakeResponses(result)),
    )

    parsed = await analyzer.analyze(
        LeadAnalysisContext(
            competitor="aiko.uz",
            post_caption="Стол",
            comment="Хочу заказать",
            username="buyer",
            previous_signals=[],
            previous_interests=[],
            evidence_ids=[7],
        )
    )

    assert parsed.evidence_ids == [7]
    assert parsed.intelligence_version == "3.0"


async def test_rules_understand_uzbek_cyrillic_price_questions():
    analyzer = RuleBasedLeadAnalyzer()
    for text in ["Нархи?", "Нархи қанча", "Нархини ёзинг", "Нархи канча?"]:
        result = await analyzer.analyze(
            LeadAnalysisContext(
                competitor="aiko.uz",
                post_caption="Обеденный комплект на 6 персон",
                comment=text,
                username="test_user",
                previous_signals=[],
                previous_interests=[],
            )
        )
        assert result.is_lead is True
        assert result.intent == Intent.PRICE
        assert result.lead_score >= 80
        assert result.language == "uz-cyrl"

async def test_rules_cover_common_uzbek_purchase_signals_without_openai():
    analyzer = RuleBasedLeadAnalyzer()
    cases = [
        ("6 кишилик борми?", Intent.AVAILABILITY),
        ("Доставка борми?", Intent.DELIVERY),
        ("20 дона керак", Intent.QUANTITY),
        ("Манзил қаерда?", Intent.LOCATION),
    ]
    for text, expected_intent in cases:
        result = await analyzer.analyze(
            LeadAnalysisContext(
                competitor="aiko.uz",
                post_caption="Плетёный обеденный комплект",
                comment=text,
                username="test_user",
                previous_signals=[],
                previous_interests=[],
            )
        )
        assert result.is_lead is True
        assert result.intent == expected_intent
        assert result.lead_score >= 70


async def test_rules_return_deep_manager_ready_analysis():
    analyzer = RuleBasedLeadAnalyzer()
    result = await analyzer.analyze(
        LeadAnalysisContext(
            competitor="aiko.uz",
            post_caption="Обеденный комплект на 6 персон",
            comment="Срочно хочу заказать сегодня, доставка есть?",
            username="buyer",
            previous_signals=[],
            previous_interests=[],
        )
    )

    assert result.is_lead is True
    assert result.intent == Intent.BUY
    assert result.funnel_stage == FunnelStage.READY_TO_BUY
    assert result.urgency == Urgency.HIGH
    assert result.purchase_horizon == PurchaseHorizon.TODAY
    assert result.confidence >= 80
    assert len(result.evidence) >= 2
    assert "10 минут" in result.recommended_action


async def test_negation_overrides_purchase_keywords():
    analyzer = RuleBasedLeadAnalyzer()
    result = await analyzer.analyze(
        LeadAnalysisContext(
            competitor="aiko.uz",
            post_caption="Стол в наличии",
            comment="Не хочу покупать, просто красиво",
            username="viewer",
            previous_signals=[],
            previous_interests=[],
        )
    )

    assert result.is_lead is False
    assert result.funnel_stage == FunnelStage.NON_COMMERCIAL
    assert "отказ" in result.risk_flags[0].lower()


async def test_rules_cover_installment_and_horeca_without_false_price_match():
    analyzer = RuleBasedLeadAnalyzer()
    contexts = [
        ("Можно в рассрочку?", Intent.PRICE, True),
        ("Для ресторана нужно 20 штук", Intent.QUANTITY, True),
        ("Сколько красоты 😍", Intent.SPAM, False),
    ]
    for text, intent, is_lead in contexts:
        result = await analyzer.analyze(
            LeadAnalysisContext(
                competitor="aiko.uz",
                post_caption="Комплект мебели для террасы",
                comment=text,
                username="buyer",
                previous_signals=[],
                previous_interests=[],
            )
        )
        assert result.intent == intent
        assert result.is_lead is is_lead


def test_rules_classify_social_congratulations_locally():
    analyzer = RuleBasedLeadAnalyzer()
    result = analyzer.classify(
        LeadAnalysisContext(
            competitor="aiko.uz",
            post_caption="Новый шоурум",
            comment="Муборак булсин, яхши кунлар куп булсин ❤️",
            username="test_user",
            previous_signals=[],
            previous_interests=[],
        )
    )
    assert result is not None
    assert result.is_lead is False
    assert result.intent == Intent.REACTION

async def test_local_rules_raise_priority_for_cross_competitor_history():
    from app.services.ai_service import (
        LeadAnalysisContext,
        RuleBasedLeadAnalyzer,
        ValidatedPreviousSignal,
    )

    analyzer = RuleBasedLeadAnalyzer()
    base_context = LeadAnalysisContext(
        competitor="aiko.uz",
        post_caption="Обеденный комплект на 6 персон",
        comment="narxi?",
        username="buyer",
        previous_signals=[],
        previous_interests=[],
    )
    comparison_context = LeadAnalysisContext(
        competitor="aiko.uz",
        post_caption="Обеденный комплект на 6 персон",
        comment="narxi?",
        username="buyer",
        previous_signals=[
            ValidatedPreviousSignal(
                lead_id=1,
                public_signal_id=1,
                evidence_ids=[101],
                competitor_id=2,
                competitor="chinar.uz",
                intent="PRICE",
                product_family="DINING_SET",
                buyer_role="B2C_CONSUMER",
                commercial_quality="MEDIUM_COMMERCIAL",
                priority_score=74,
                confidence=88,
                observed_at="2026-08-25T10:00:00+00:00",
                vertical="FURNITURE",
            )
        ],
        previous_interests=["DINING_SET"],
    )

    base = analyzer.classify(base_context)
    comparison = analyzer.classify(comparison_context)

    assert base is not None and comparison is not None
    assert comparison.lead_score > base.lead_score
    assert comparison.lead_score <= 99


def test_commercial_plus_defers_to_openai_for_caption_context():
    analyzer = RuleBasedLeadAnalyzer()
    for comment in ("+", "+?", "+!", "+ 🙏", "+..."):
        result = analyzer.classify(
            LeadAnalysisContext(
                competitor="aiko.uz",
                post_caption="Оставьте плюс, чтобы получить каталог и цены",
                comment=comment,
                username="buyer",
                previous_signals=[],
                previous_interests=[],
            )
        )
        assert result is None


def test_watch_price_question_is_rejected_without_openai():
    analyzer = RuleBasedLeadAnalyzer()
    result = analyzer.classify(
        LeadAnalysisContext(
            competitor="aiko.uz",
            post_caption="Rolex Submariner yangi kolleksiya soatlar",
            comment="Narxi qancha?",
            username="buyer",
            previous_signals=[],
            previous_interests=[],
        )
    )
    assert result is not None
    assert result.is_lead is False
    assert result.intent == Intent.OTHER


def test_generic_price_without_furniture_context_defers_to_openai():
    analyzer = RuleBasedLeadAnalyzer()
    result = analyzer.classify(
        LeadAnalysisContext(
            competitor="aiko.uz",
            post_caption="Новинки сезона",
            comment="Narxi qancha?",
            username="buyer",
            previous_signals=[],
            previous_interests=[],
        )
    )
    assert result is None
