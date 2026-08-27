from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select

from app.db.models import AIRequest, AIRequestStatus
from app.schemas.leads import BuyerRole, FunnelStage, Intent, LeadAnalysis, PurchaseHorizon, Urgency
from app.services.ai_service import (
    BudgetedCachedOpenAIAnalyzer,
    LeadAnalysisContext,
    OpenAILeadAnalyzer,
)
from app.services.usage_service import ExternalUsageService


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
    analyzer = BudgetedCachedOpenAIAnalyzer(mock_inner, session_factory, usage_svc, enabled=True, daily_limit=10)

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
