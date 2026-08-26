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

