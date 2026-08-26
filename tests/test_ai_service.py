from types import SimpleNamespace

from app.schemas.leads import Intent, LeadAnalysis
from app.services.ai_service import LeadAnalysisContext, OpenAILeadAnalyzer


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

