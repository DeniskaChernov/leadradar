from decimal import Decimal

from sqlalchemy import func, select

from app.db.models import (
    AIFeedback,
    Comment,
    Contact,
    ContactEvent,
    ContactEventType,
    Deal,
    DealStatus,
    Lead,
    LeadStatus,
    Post,
)
from app.providers.mock import MockInstagramProvider
from app.services.contact_service import ContactService
from app.services.instagram_monitor import InstagramMonitor
from app.services.lead_service import LeadService
from app.services.lead_workflow_service import LeadWorkflowService
from tests.test_lead_service import StaticAnalyzer
from tests.test_monitor import RecordingNotifier


async def test_mock_hot_to_taken_to_won_acceptance_flow(session_factory):
    notifier = RecordingNotifier()
    monitor = InstagramMonitor(
        session_factory=session_factory,
        provider=MockInstagramProvider(),
        contact_service=ContactService(session_factory),
        lead_service=LeadService(session_factory, StaticAnalyzer(), 70),
        notifier=notifier,
        competitors=["aiko.uz"],
        process_existing_comments=True,
    )

    cycle = await monitor.run_cycle()

    assert cycle.comments_created == 1
    assert cycle.leads_created == 1
    assert cycle.hot_notifications == 1
    assert len(notifier.lead_ids) == 1
    lead_id = notifier.lead_ids[0]

    workflow = LeadWorkflowService(session_factory, 70)
    taken = await workflow.assign_manager(lead_id, 1001)
    deal = await workflow.create_deal(lead_id, 1001)
    won = await workflow.win_deal(
        deal.id,
        1001,
        product_name="6-person dining set",
        amount=Decimal("4500000"),
        quantity=1,
    )

    assert taken.assigned_manager_telegram_id == 1001
    assert won.status == DealStatus.WON

    async with session_factory() as session:
        assert await session.scalar(select(func.count(Contact.id))) == 1
        assert await session.scalar(select(func.count(Post.id))) == 1
        assert await session.scalar(select(func.count(Comment.id))) == 1
        assert await session.scalar(select(func.count(Lead.id))) == 1
        assert await session.scalar(select(func.count(Deal.id))) == 1
        assert await session.scalar(select(func.count(AIFeedback.id))) == 1
        lead = await session.get(Lead, lead_id)
        assert lead is not None
        assert lead.status == LeadStatus.WON
        event_types = set((await session.scalars(select(ContactEvent.event_type))).all())
        assert {
            ContactEventType.COMMENT_FOUND,
            ContactEventType.LEAD_CREATED,
            ContactEventType.MANAGER_ASSIGNED,
            ContactEventType.DEAL_CREATED,
            ContactEventType.DEAL_WON,
        } <= event_types

