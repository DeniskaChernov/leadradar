from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.db.models import (
    AIFeedback,
    Contact,
    ContactEvent,
    ContactEventType,
    ContactTask,
    DealSaleSnapshot,
    DealStatus,
    Lead,
    LeadStatus,
    Product,
    Vertical,
)
from app.services.contact_service import ContactService
from app.services.crm_service import CRMService
from app.services.lead_service import LeadService
from app.services.lead_workflow_service import (
    LeadAlreadyAssignedError,
    LeadWorkflowError,
    LeadWorkflowService,
)
from tests.test_contact_service import make_comment, make_post
from tests.test_lead_service import StaticAnalyzer


async def create_lead(session_factory, comment_id="comment-1", user_id="user-1"):
    comment = make_comment(comment_id).model_copy(
        update={
            "platform_user_id": user_id,
            "username": user_id,
            "profile_url": f"https://www.instagram.com/{user_id}/",
        }
    )
    signal = await ContactService(session_factory).persist_signal(
        make_post(),
        comment,
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
    repeated = await workflow.win_deal(
        deal.id,
        1001,
        product_name="6-person dining set",
        amount=Decimal("4500000"),
        quantity=1,
    )

    assert deal.status == DealStatus.WON
    assert repeated.id == deal.id
    async with session_factory() as session:
        feedback = await session.scalar(
            select(AIFeedback).where(AIFeedback.lead_id == lead_id)
        )
        assert feedback is not None
        assert feedback.deal_won is True
        assert feedback.deal_amount == Decimal("4500000")
        won_events = await session.scalar(
            select(func.count(ContactEvent.id)).where(
                ContactEvent.event_type == ContactEventType.DEAL_WON
            )
        )
        assert won_events == 1
        snapshots = await session.scalar(select(func.count(DealSaleSnapshot.id)))
        assert snapshots == 1

    with pytest.raises(LeadWorkflowError, match="cannot be changed"):
        await workflow.win_deal(
            deal.id,
            1001,
            product_name="another product",
            amount=Decimal("4500000"),
            quantity=1,
        )
    with pytest.raises(LeadWorkflowError, match="cannot become LOST"):
        await workflow.lose_deal(deal.id, 1001, reason="changed")


async def test_deal_lost_updates_feedback_and_event(session_factory):
    lead_id = await create_lead(session_factory, "comment-lost")
    workflow = LeadWorkflowService(session_factory, 70)
    await workflow.assign_manager(lead_id, 1001)
    deal = await workflow.create_deal(lead_id, 1001)

    deal = await workflow.lose_deal(deal.id, 1001, reason="дорого")
    repeated = await workflow.lose_deal(deal.id, 1001, reason="дорого")

    assert deal.status == DealStatus.LOST
    assert repeated.id == deal.id
    async with session_factory() as session:
        feedback = await session.scalar(
            select(AIFeedback).where(AIFeedback.lead_id == lead_id)
        )
        assert feedback is not None
        assert feedback.deal_won is False
        assert feedback.lost_reason == "дорого"


async def test_crm_rejects_cross_contact_links_and_deduplicates_same_open_task(
    session_factory,
):
    first_lead_id = await create_lead(
        session_factory,
        "contact-first",
        "user-first",
    )
    second_lead_id = await create_lead(
        session_factory,
        "contact-second",
        "user-second",
    )
    async with session_factory() as session:
        first_lead = await session.get(Lead, first_lead_id)
        assert first_lead is not None
        first_contact_id = first_lead.contact_id

    crm = CRMService(session_factory)
    due_at = datetime.now(UTC) + timedelta(days=1)

    with pytest.raises(LeadWorkflowError, match="не принадлежит"):
        await crm.record_customer_reply(
            first_contact_id,
            1001,
            text="ответ",
            lead_id=second_lead_id,
        )
    with pytest.raises(LeadWorkflowError, match="не принадлежит"):
        await crm.schedule_contact(
            first_contact_id,
            1001,
            due_at=due_at,
            note="Повторный контакт",
            lead_id=second_lead_id,
        )

    first_task = await crm.schedule_contact(
        first_contact_id,
        1001,
        due_at=due_at,
        note="Повторный контакт",
        lead_id=first_lead_id,
    )
    repeated_task = await crm.schedule_contact(
        first_contact_id,
        1001,
        due_at=due_at,
        note="Повторный контакт",
        lead_id=first_lead_id,
    )
    assert repeated_task.id == first_task.id

    async with session_factory() as session:
        task_count = await session.scalar(select(func.count(ContactTask.id)))
        event_count = await session.scalar(
            select(func.count(ContactEvent.id)).where(
                ContactEvent.event_type == ContactEventType.NEXT_CONTACT_SCHEDULED
            )
        )
    assert task_count == 1
    assert event_count == 1


async def test_won_deal_snapshots_confirmed_product_facts(session_factory):
    lead_id = await create_lead(session_factory, "catalog-sale")
    workflow = LeadWorkflowService(session_factory, 70)
    await workflow.assign_manager(lead_id, 1001)
    deal = await workflow.create_deal(lead_id, 1001)
    async with session_factory() as session:
        product = Product(
            canonical_key="catalog-chair",
            name="CORDA",
            vertical=Vertical.FURNITURE,
            category="CHAIR",
            category_confirmed_at=datetime.now(UTC),
            category_confirmed_by=1001,
            price=Decimal("33"),
            price_confirmed_at=datetime.now(UTC),
            price_confirmed_by=1001,
            currency="USD",
            cogs=Decimal("20"),
            cogs_confirmed_at=datetime.now(UTC),
            cogs_confirmed_by=1001,
            colors_json=[],
            b2b_suitability="UNCONFIRMED",
            import_source="MANUAL",
            active=True,
        )
        session.add(product)
        await session.commit()
        product_id = product.id

    won = await workflow.win_deal(
        deal.id,
        1001,
        product_name="ignored free text",
        product_id=product_id,
        amount=Decimal("4500000"),
        quantity=2,
    )
    assert won.product_id == product_id
    assert won.product_name == "CORDA"

    async with session_factory() as session:
        snapshot = await session.scalar(
            select(DealSaleSnapshot).where(DealSaleSnapshot.deal_id == won.id)
        )
    assert snapshot is not None
    assert snapshot.product_id == product_id
    assert snapshot.product_name == "CORDA"
    assert snapshot.catalog_price == Decimal("33")
    assert snapshot.cogs == Decimal("20")
    assert snapshot.quantity == 2
