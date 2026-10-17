import json

import httpx
import pytest
from openai import AsyncOpenAI
from sqlalchemy import select

from app.db.models import (
    AIRequest,
    AIRequestStatus,
    CostEvent,
    ExternalBudgetReservation,
    ReservationStatus,
)
from app.providers.base import ProviderCallUncertainError
from app.providers.budgeted import BudgetedInstagramProvider, ScanBudget
from app.providers.scrapecreators import ScrapeCreatorsProvider
from app.schemas.leads import Intent, LeadAnalysis
from app.services.ai_service import (
    AIOutputError,
    BudgetedCachedOpenAIAnalyzer,
    LeadAnalysisContext,
    OpenAILeadAnalyzer,
)
from app.services.usage_service import ExternalUsageService
from tests.conftest import seed_scrapecreators_instagram_policy
from tests.test_lead_workflow import create_lead


def context(lead_id=None):
    return LeadAnalysisContext(
        competitor="aiko.uz", post_caption="Плетёный стул", comment="Цена?",
        username="public-buyer", previous_signals=[], previous_interests=[],
        lead_id=lead_id,
    )


def response_envelope(text, *, status="completed", input_tokens=120, output_tokens=60):
    return {
        "id": "resp_public_fixture", "object": "response", "created_at": 1,
        "model": "gpt-5-mini", "status": status,
        "incomplete_details": {"reason": "max_output_tokens"} if status == "incomplete" else None,
        "output": [{"id": "msg_public_fixture", "type": "message", "role": "assistant",
                    "status": "completed", "content": [{"type": "output_text", "text": text,
                                                          "annotations": []}]}],
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens,
                  "total_tokens": input_tokens + output_tokens},
    }


@pytest.mark.parametrize("status", ["completed", "incomplete"])
async def test_real_sdk_truncated_response_preserves_usage_and_is_retryable(status):
    requests = []

    async def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=response_envelope('{"is_lead":', status=status))

    async with AsyncOpenAI(api_key="test-local", max_retries=0,
                          http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))) as client:
        analyzer = OpenAILeadAnalyzer("unused", "gpt-5-mini", client=client)
        with pytest.raises(AIOutputError) as error:
            await analyzer.analyze(context())

    assert error.value.token_usage == (120, 60)
    assert error.value.response_id == "resp_public_fixture"
    assert BudgetedCachedOpenAIAnalyzer._classify_failure(error.value)[0] == AIRequestStatus.RETRYABLE
    assert len(requests) == 1
    assert requests[0]["max_output_tokens"] == 3000


async def test_invalid_paid_output_is_accounted_once_and_explicit_retry_can_succeed(session_factory):
    lead_id = await create_lead(session_factory)
    analysis = LeadAnalysis(is_lead=True, lead_score=85, intent=Intent.PRICE,
                            product_category="WICKER_CHAIR", language="ru", reason="Запрос цены")
    payloads = [response_envelope('{"is_lead":', status="incomplete"),
                response_envelope(analysis.model_dump_json(), input_tokens=130, output_tokens=90)]
    calls = []

    async def handler(request):
        calls.append(request)
        return httpx.Response(200, json=payloads[len(calls) - 1])

    usage = ExternalUsageService(session_factory)
    async with AsyncOpenAI(api_key="test-local", max_retries=0,
                          http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))) as client:
        analyzer = BudgetedCachedOpenAIAnalyzer(
            OpenAILeadAnalyzer("unused", "gpt-5-mini", client=client), session_factory, usage,
            enabled=True, daily_limit=10,
        )
        with pytest.raises(AIOutputError):
            await analyzer.analyze(context(lead_id))
        async with session_factory() as session:
            request = await session.scalar(select(AIRequest))
            assert request.status == AIRequestStatus.RETRYABLE
            assert (request.input_tokens, request.output_tokens) == (120, 60)
        assert len(calls) == 1
        assert await usage.active_reservations_today("openai") == 0
        assert await usage.used_today("openai") == 1

        result = await analyzer.analyze(context(lead_id))
        cached = await analyzer.analyze(context(lead_id))
        assert result.lead_score == cached.lead_score == 85

    assert len(calls) == 2
    async with session_factory() as session:
        reservations = list(await session.scalars(select(ExternalBudgetReservation)))
        costs = list(await session.scalars(select(CostEvent).order_by(CostEvent.id)))
        request = await session.scalar(select(AIRequest))
    assert {row.status for row in reservations} == {ReservationStatus.FINALIZED}
    assert len(costs) == 2
    assert [(row.input_tokens, row.output_tokens) for row in costs] == [(120, 60), (130, 90)]
    assert costs[0].details_json["billing_state"] == "RESPONSE_RECEIVED_INVALID_OUTPUT"
    assert request.status == AIRequestStatus.SUCCEEDED and request.attempt_count == 2
    assert await usage.used_today("openai") == 2


async def test_default_openai_client_has_one_attempt_and_timeout_below_lease():
    analyzer = OpenAILeadAnalyzer("test-local", "gpt-5-mini")
    try:
        assert analyzer.client.max_retries == 0
        assert analyzer.client.timeout == 60.0
    finally:
        await analyzer.client.close()


@pytest.mark.parametrize("charged", [0, 1, None])
async def test_provider_500_retains_only_explicit_credit_proof(session_factory, charged):
    await seed_scrapecreators_instagram_policy(session_factory)
    calls = []

    async def handler(request):
        calls.append(request)
        body = {"error": "upstream unavailable"}
        if charged is not None:
            body.update(credits_charged=charged, credits_remaining=100)
        return httpx.Response(500, json=body)

    usage = ExternalUsageService(session_factory)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = BudgetedInstagramProvider(
            ScrapeCreatorsProvider("test-local", client=client, max_attempts=3),
            usage, enabled=True, daily_limit=10, scan_budget=ScanBudget(default_limit=5),
        )
        with pytest.raises(ProviderCallUncertainError):
            await provider.get_reels("aiko.uz")

    assert len(calls) == 1
    async with session_factory() as session:
        reservation = await session.scalar(select(ExternalBudgetReservation))
        costs = list(await session.scalars(select(CostEvent)))
    if charged is None:
        assert reservation.status == ReservationStatus.UNCERTAIN and costs == []
    else:
        assert reservation.status == ReservationStatus.FINALIZED
        assert reservation.actual_units == charged
        assert len(costs) == 1 and costs[0].units == charged
        assert costs[0].unit_source == "PROVIDER_CONFIRMED"
