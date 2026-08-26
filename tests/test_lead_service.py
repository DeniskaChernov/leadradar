from sqlalchemy import func, select

from app.db.models import AIFeedback, ContactEvent, ContactEventType, Lead, LeadStatus
from app.schemas.leads import Intent, LeadAnalysis
from app.services.contact_service import ContactService
from app.services.lead_service import LeadService
from tests.test_contact_service import make_comment, make_post


class StaticAnalyzer:
    async def analyze(self, context):
        return LeadAnalysis(
            is_lead=True,
            lead_score=91,
            intent=Intent.PRICE,
            product_category="DINING_SET",
            language="uz",
            reason="CTA asks for plus to receive a price",
        )


async def test_lead_creation_feedback_event_and_hot_threshold(session_factory):
    signal = await ContactService(session_factory).persist_signal(make_post(), make_comment())
    service = LeadService(session_factory, StaticAnalyzer(), hot_threshold=70)

    result = await service.process_signal(signal)
    duplicate = await service.process_signal(signal)

    assert result is not None
    assert result.created is True
    assert result.is_hot is True
    assert result.status == LeadStatus.NEW
    assert duplicate is not None
    assert duplicate.created is False

    async with session_factory() as session:
        lead = await session.scalar(select(Lead))
        assert lead is not None
        assert lead.analysis_details is not None
        assert lead.analysis_details["confidence"] == 50
        assert await session.scalar(select(func.count(Lead.id))) == 1
        assert await session.scalar(select(func.count(AIFeedback.id))) == 1
        assert (
            await session.scalar(
                select(func.count(ContactEvent.id)).where(
                    ContactEvent.event_type == ContactEventType.LEAD_CREATED
                )
            )
            == 1
        )


async def test_deep_analysis_backfill_is_idempotent(session_factory):
    signal = await ContactService(session_factory).persist_signal(make_post(), make_comment())
    service = LeadService(session_factory, StaticAnalyzer(), hot_threshold=70)
    await service.process_signal(signal)

    async with session_factory() as session:
        lead = await session.scalar(select(Lead))
        assert lead is not None
        lead.analysis_details = None
        await session.commit()

    first = await service.backfill_analysis_details()
    second = await service.backfill_analysis_details()

    assert first == 1
    assert second == 0
    async with session_factory() as session:
        lead = await session.scalar(select(Lead))
        assert lead is not None
        assert lead.analysis_details is not None
        assert lead.analysis_details["lead_score"] == 91
        assert lead.analysis_details["recommended_action"]
