from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.db.models import AIFeedback, Lead, LeadStatus
from app.schemas.leads import Intent, LeadAnalysis
from app.services.ai_service import AIAnalysisError
from app.services.contact_service import ContactService
from app.services.lead_service import LeadService
from tests.test_contact_service import make_comment, make_post


class RecoveringAnalyzer:
    def __init__(self):
        self.available = False

    async def analyze(self, context):
        if not self.available:
            raise AIAnalysisError("temporary")
        return LeadAnalysis(
            is_lead=True,
            lead_score=88,
            intent=Intent.PRICE,
            product_category="DINING_SET",
            language="uz",
            reason="Recovered analysis",
        )


async def test_ai_pending_is_retried_and_completed(session_factory):
    signal = await ContactService(session_factory).persist_signal(make_post(), make_comment())
    analyzer = RecoveringAnalyzer()
    service = LeadService(session_factory, analyzer, 70)

    pending = await service.process_signal(signal)
    assert pending is not None
    assert pending.status == LeadStatus.AI_PENDING

    analyzer.available = True
    completed = await service.retry_pending()

    assert len(completed) == 1
    assert completed[0].status == LeadStatus.NEW
    assert completed[0].is_hot is True
    async with session_factory() as session:
        feedback = await session.scalar(
            select(AIFeedback).where(AIFeedback.lead_id == completed[0].lead_id)
        )
        assert feedback is not None
        assert feedback.predicted_score == 88


async def test_retry_pending_recovers_stale_analyzing(session_factory):
    signal = await ContactService(session_factory).persist_signal(make_post(), make_comment())
    analyzer = RecoveringAnalyzer()
    service = LeadService(session_factory, analyzer, 70)
    pending = await service.process_signal(signal)
    assert pending is not None
    assert pending.status == LeadStatus.AI_PENDING

    async with session_factory() as session:
        lead = await session.get(Lead, pending.lead_id)
        assert lead is not None
        lead.status = LeadStatus.ANALYZING
        lead.ai_last_attempt_at = datetime.now(UTC) - timedelta(minutes=20)
        await session.commit()

    analyzer.available = True
    completed = await service.retry_pending()

    assert len(completed) == 1
    assert completed[0].status == LeadStatus.NEW
