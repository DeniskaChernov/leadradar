from decimal import Decimal

import pytest
from sqlalchemy import select

from app.db.models import (
    AIFeedback,
    Contact,
    ContactEvent,
    ContactEventType,
    DealStatus,
    LeadStatus,
)
from app.services.contact_service import ContactService
from app.services.lead_service import LeadService
from app.services.lead_workflow_service import LeadAlreadyAssignedError, LeadWorkflowService
from tests.test_contact_service import make_comment, make_post
from tests.test_lead_service import StaticAnalyzer


async def create_lead(session_factory, comment_id="comment-1"):
    signal = await ContactService(session_factory).persist_signal(
        make_post(), make_comment(comment_id)
    )
    result = await LeadService(session_factory, StaticAnalyzer(), 70).process_signal(signal)
    assert result is not None
    return result.lead_id


async def test_atomic_manager_assignment_and_double_assignment_protection(session_factory):
    lead_id = await create_lead(session_factory)
    workflow = LeadWorkflowService(session_factory, 70)

    assigned = await workflow.assign_manager(lead_id, 1001)
    same_manager = await workflow.assign_manager(lead_id, 1001)

    assert assigned.status == LeadStatus.TAKEN
    assert same_manager.assigned_manager_telegram_id == 1001
    with pytest.raises(LeadAlreadyAssignedError):
        await workflow.assign_manager(lead_id, 2002)

    async with session_factory() as session:
        contact = await session.get(Contact, assigned.contact_id)
        assert contact is not None
        assert contact.assigned_manager_telegram_id == 1001
        events = (
            await session.scalars(
                select(ContactEvent).where(
                    ContactEvent.event_type == ContactEventType.MANAGER_ASSIGNED
                )
            )
        ).all()
        assert len(events) == 1


async def test_not_lead_updates_feedback_without_deleting_signal(session_factory):
    lead_id = await create_lead(session_factory)
    workflow = LeadWorkflowService(session_factory, 70)

    lead = await workflow.mark_not_lead(lead_id, 1001)

    assert lead.status == LeadStatus.NOT_LEAD
    async with session_factory() as session:
        feedback = await session.scalar(
            select(AIFeedback).where(AIFeedback.lead_id == lead_id)
        )
        assert feedback is not None
        assert feedback.manager_is_lead is False


async def test_deal_won_updates_lead_feedback_and_event(session_factory):
    lead_id = await create_lead(session_factory)
    workflow = LeadWorkflowService(session_factory, 70)
    await workflow.assign_manager(lead_id, 1001)
    deal = await workflow.create_deal(lead_id, 1001)

    deal = await workflow.win_deal(
        deal.id,
        1001,
        product_name="6-person dining set",
        amount=Decimal("4500000"),
        quantity=1,
    )

    assert deal.status == DealStatus.WON
    async with session_factory() as session:
        feedback = await session.scalar(
            select(AIFeedback).where(AIFeedback.lead_id == lead_id)
        )
        assert feedback is not None
        assert feedback.deal_won is True
        assert feedback.deal_amount == Decimal("4500000")


async def test_deal_lost_updates_feedback_and_event(session_factory):
    lead_id = await create_lead(session_factory, "comment-lost")
    workflow = LeadWorkflowService(session_factory, 70)
    await workflow.assign_manager(lead_id, 1001)
    deal = await workflow.create_deal(lead_id, 1001)

    deal = await workflow.lose_deal(deal.id, 1001, reason="дорого")

    assert deal.status == DealStatus.LOST
    async with session_factory() as session:
        feedback = await session.scalar(
            select(AIFeedback).where(AIFeedback.lead_id == lead_id)
        )
        assert feedback is not None
        assert feedback.deal_won is False
        assert feedback.lost_reason == "дорого"
