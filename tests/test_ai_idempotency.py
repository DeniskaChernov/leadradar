import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select

from app.db.models import AIRequest, AIRequestStatus
from app.schemas.leads import BuyerRole, FunnelStage, Intent, LeadAnalysis, PurchaseHorizon, Urgency
from app.services.ai_service import (
    AIAnalysisError,
    BudgetedCachedOpenAIAnalyzer,
    LeadAnalysisContext,
    OpenAILeadAnalyzer,
    ValidatedPreviousSignal,
)
from app.services.usage_service import ExternalUsageService
from tests.test_lead_workflow import create_lead


def _sample_analysis():
    return LeadAnalysis(
        is_lead=True,
        lead_score=85,
        intent=Intent.PRICE,
        product_category="RATTAN_SOFA",
        language="RU",
        reason="Explicit price request on sofa post",
        confidence=90,
        urgency=Urgency.MEDIUM,
        funnel_stage=FunnelStage.CONSIDERATION,
        purchase_horizon=PurchaseHorizon.THIS_WEEK,
        buyer_role=BuyerRole.B2C_CONSUMER,
        recommended_action="Send sofa pricing",
    )


@pytest.mark.asyncio
async def test_ai_request_idempotency_prevents_duplicate_calls(session_factory):
    lead_id = await create_lead(session_factory)
    mock_inner = MagicMock(spec=OpenAILeadAnalyzer)
    mock_inner.model = "gpt-5-mini"
    mock_inner.analyze = AsyncMock(return_value=_sample_analysis())

    usage_svc = ExternalUsageService(session_factory)
    analyzer = BudgetedCachedOpenAIAnalyzer(
        mock_inner,
        session_factory,
        usage_svc,
        enabled=True,
        daily_limit=10,
        worker_id="worker-1",
    )

    ctx = LeadAnalysisContext(
        competitor="aiko.uz",
        post_caption="Плетёный диван",
        comment="Цена?",
        username="john_doe",
        previous_signals=[],
        previous_interests=[],
        lead_id=lead_id,
    )

    # 1. First call executes inner analysis
    res1 = await analyzer.analyze(ctx)
    assert res1.lead_score == 85
    assert mock_inner.analyze.call_count == 1

    # 2. Second call with same context returns from AIRequest ledger (zero additional inner calls)
    res2 = await analyzer.analyze(ctx)
    assert res2.lead_score == 85
    assert mock_inner.analyze.call_count == 1

    # 3. Verify ledger record
    async with session_factory() as session:
        reqs = (await session.scalars(select(AIRequest))).all()
        assert len(reqs) == 1
        assert reqs[0].status == AIRequestStatus.SUCCEEDED
        assert reqs[0].context_fingerprint == analyzer.context_fingerprint(ctx)


@pytest.mark.asyncio
async def test_context_fingerprint_deterministic_and_sensitive(session_factory):
    mock_inner = MagicMock()
    mock_inner.model = "gpt-5-mini"
    usage_svc = ExternalUsageService(session_factory)
    analyzer = BudgetedCachedOpenAIAnalyzer(
        mock_inner, session_factory, usage_svc, enabled=True, daily_limit=10
    )

    ctx1 = LeadAnalysisContext(
        competitor="aiko.uz",
        post_caption="Диван",
        comment="Цена?",
        username="user1",
        previous_signals=[],
        previous_interests=[],
    )
    ctx2 = LeadAnalysisContext(
        competitor="aiko.uz",
        post_caption="Диван",
        comment="Цена?",
        username="user1",
        previous_signals=[],
        previous_interests=[],
    )
    ctx3 = LeadAnalysisContext(
        competitor="aiko.uz",
        post_caption="Диван",
        comment="В наличии?",
        username="user1",
        previous_signals=[],
        previous_interests=[],
    )

    # Identical contexts produce identical fingerprint
    assert analyzer.context_fingerprint(ctx1) == analyzer.context_fingerprint(ctx2)
    # Different comment produces different fingerprint
    assert analyzer.context_fingerprint(ctx1) != analyzer.context_fingerprint(ctx3)

    ctx_without_validated_history = LeadAnalysisContext(
        competitor="aiko.uz",
        post_caption="Диван",
        comment="Цена?",
        username="user1",
        previous_signals=[],
        previous_interests=[],
    )
    assert analyzer.context_fingerprint(ctx1) == analyzer.context_fingerprint(
        ctx_without_validated_history
    )

    ctx_with_commercial_history = LeadAnalysisContext(
        competitor="aiko.uz",
        post_caption="Диван",
        comment="Цена?",
        username="user1",
        previous_signals=[
            ValidatedPreviousSignal(
                lead_id=1,
                public_signal_id=1,
                evidence_ids=[11],
                competitor_id=2,
                competitor="other",
                intent="DELIVERY",
                product_family="SOFA",
                buyer_role="B2C_CONSUMER",
                commercial_quality="MEDIUM_COMMERCIAL",
                priority_score=76,
                confidence=86,
                observed_at="2026-08-27T10:00:00Z",
                vertical="FURNITURE",
            )
        ],
        previous_interests=[],
    )
    assert analyzer.context_fingerprint(ctx1) != analyzer.context_fingerprint(
        ctx_with_commercial_history
    )


@pytest.mark.asyncio
async def test_two_ai_workers_make_one_external_call(file_session_factory):
    lead_id = await create_lead(file_session_factory)
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_analysis(_context):
        started.set()
        await release.wait()
        return _sample_analysis()

    inner = MagicMock(spec=OpenAILeadAnalyzer)
    inner.model = "gpt-5-mini"
    inner.analyze = AsyncMock(side_effect=slow_analysis)
    context = LeadAnalysisContext(
        competitor="aiko.uz",
        post_caption="Плетёный диван",
        comment="Цена?",
        username="john_doe",
        previous_signals=[],
        previous_interests=[],
        lead_id=lead_id,
    )
    first = BudgetedCachedOpenAIAnalyzer(
        inner,
        file_session_factory,
        ExternalUsageService(file_session_factory),
        enabled=True,
        daily_limit=10,
        worker_id="worker-a",
    )
    second = BudgetedCachedOpenAIAnalyzer(
        inner,
        file_session_factory,
        ExternalUsageService(file_session_factory),
        enabled=True,
        daily_limit=10,
        worker_id="worker-b",
    )

    first_task = asyncio.create_task(first.analyze(context))
    await started.wait()
    with pytest.raises(AIAnalysisError, match="другим процессом"):
        await second.analyze(context)
    release.set()
    result = await first_task

    assert result.lead_score == 85
    assert inner.analyze.await_count == 1


@pytest.mark.asyncio
async def test_five_ai_workers_make_at_most_one_external_call(file_session_factory):
    lead_id = await create_lead(file_session_factory)
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_analysis(_context):
        started.set()
        await release.wait()
        return _sample_analysis()

    inner = MagicMock(spec=OpenAILeadAnalyzer)
    inner.model = "gpt-5-mini"
    inner.analyze = AsyncMock(side_effect=slow_analysis)
    context = LeadAnalysisContext(
        competitor="aiko.uz",
        post_caption="Плетёный диван",
        comment="Цена?",
        username="five-workers",
        previous_signals=[],
        previous_interests=[],
        lead_id=lead_id,
    )
    analyzers = [
        BudgetedCachedOpenAIAnalyzer(
            inner,
            file_session_factory,
            ExternalUsageService(file_session_factory),
            enabled=True,
            daily_limit=10,
            worker_id=f"worker-{index}",
        )
        for index in range(5)
    ]
    first = asyncio.create_task(analyzers[0].analyze(context))
    await started.wait()
    competitors = await asyncio.gather(
        *(analyzer.analyze(context) for analyzer in analyzers[1:]),
        return_exceptions=True,
    )
    release.set()
    await first

    assert all(isinstance(result, AIAnalysisError) for result in competitors)
    assert inner.analyze.await_count == 1


@pytest.mark.asyncio
async def test_max_attempts_blocks_fourth_paid_call(session_factory):
    lead_id = await create_lead(session_factory)
    inner = MagicMock(spec=OpenAILeadAnalyzer)
    inner.model = "gpt-5-mini"
    async def timeout_failure(_context):
        try:
            raise TimeoutError("provider timeout")
        except TimeoutError as exc:
            raise AIAnalysisError("provider failed") from exc

    inner.analyze = AsyncMock(side_effect=timeout_failure)
    analyzer = BudgetedCachedOpenAIAnalyzer(
        inner,
        session_factory,
        ExternalUsageService(session_factory),
        enabled=True,
        daily_limit=10,
        worker_id="retry-worker",
        max_attempts=3,
    )
    context = LeadAnalysisContext(
        competitor="aiko.uz",
        post_caption="Диван",
        comment="Цена?",
        username="retry-user",
        previous_signals=[],
        previous_interests=[],
        lead_id=lead_id,
    )

    for _ in range(3):
        with pytest.raises(AIAnalysisError, match="provider failed"):
            await analyzer.analyze(context)
    with pytest.raises(AIAnalysisError):
        await analyzer.analyze(context)

    assert inner.analyze.await_count == 3
    async with session_factory() as session:
        request = await session.scalar(select(AIRequest))
    assert request is not None
    assert request.status == AIRequestStatus.PERMANENT_FAILURE
    assert request.attempt_count == 3


@pytest.mark.asyncio
async def test_stale_claim_takeover_reuses_ledger_row(session_factory):
    lead_id = await create_lead(session_factory)
    inner = MagicMock(spec=OpenAILeadAnalyzer)
    inner.model = "gpt-5-mini"
    analyzer = BudgetedCachedOpenAIAnalyzer(
        inner,
        session_factory,
        ExternalUsageService(session_factory),
        enabled=True,
        daily_limit=10,
        worker_id="takeover-worker",
    )
    context = LeadAnalysisContext(
        competitor="aiko.uz",
        post_caption="Диван",
        comment="Есть доставка?",
        username="stale-user",
        previous_signals=[],
        previous_interests=[],
        lead_id=lead_id,
    )
    fingerprint = analyzer.context_fingerprint(context)
    _cached, request_id, first_token = await analyzer._claim_request(
        lead_id, fingerprint, datetime.now(UTC)
    )
    assert request_id is not None and first_token is not None
    async with session_factory() as session:
        request = await session.get(AIRequest, request_id)
        assert request is not None
        request.claim_expires_at = datetime.now(UTC) - timedelta(days=1)
        await session.commit()

    _cached, takeover_id, takeover_token = await analyzer._claim_request(
        lead_id, fingerprint, datetime.now(UTC)
    )

    assert takeover_id == request_id
    assert takeover_token != first_token
    async with session_factory() as session:
        requests = (await session.scalars(select(AIRequest))).all()
    assert len(requests) == 1
    assert requests[0].attempt_count == 2
