"""CRM commands commit as one operation and preserve terminal decisions under retries."""

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import (
    AIFeedback,
    Contact,
    ContactEvent,
    ContactEventType,
    ContactTask,
    Deal,
    Lead,
    LeadStatus,
    TaskStatus,
)
from app.db.repositories.events import ContactEventRepository
from app.services.crm_service import CRMService
from app.services.lead_workflow_service import (
    LeadAlreadyAssignedError,
    LeadWorkflowError,
    LeadWorkflowService,
)
from app.services.monitor_controller import MonitorController
from app.web.app import build_web_app
from app.web.queries import WebQueryService
from tests.test_lead_workflow import create_lead


async def _event_count(factory, lead_id, event_type=None):
    async with factory() as session:
        query = select(func.count(ContactEvent.id)).where(ContactEvent.lead_id == lead_id)
        if event_type is not None:
            query = query.where(ContactEvent.event_type == event_type)
        return await session.scalar(query)


async def test_board_jump_rolls_back_every_stage_on_event_failure(session_factory, monkeypatch):
    lead_id = await create_lead(session_factory)
    original_count = await _event_count(session_factory, lead_id)
    original_add = ContactEventRepository.add

    async def fail_final_event(self, contact_id, event_type, **kwargs):
        if kwargs.get("payload", {}).get("to") == LeadStatus.OFFER_SENT.value:
            raise RuntimeError("final event could not be persisted")
        return await original_add(self, contact_id, event_type, **kwargs)

    monkeypatch.setattr(ContactEventRepository, "add", fail_final_event)
    with pytest.raises(RuntimeError, match="final event"):
        await CRMService(session_factory).move_lead_toward(lead_id, 1001, LeadStatus.OFFER_SENT)

    async with session_factory() as session:
        lead = await session.get(Lead, lead_id)
        contact = await session.get(Contact, lead.contact_id)
        feedback = await session.scalar(select(AIFeedback).where(AIFeedback.lead_id == lead_id))
        assert lead.status == LeadStatus.NEW
        assert lead.assigned_manager_telegram_id is None
        assert contact.assigned_manager_telegram_id is None
        assert contact.last_contacted_at is None
        assert feedback.manager_is_lead is None
    assert await _event_count(session_factory, lead_id) == original_count


async def test_board_jump_retry_keeps_one_history_chain(session_factory):
    lead_id = await create_lead(session_factory)
    crm = CRMService(session_factory)
    first = await crm.move_lead_toward(lead_id, 1001, LeadStatus.OFFER_SENT)
    event_count = await _event_count(session_factory, lead_id)
    repeated = await crm.move_lead_toward(lead_id, 1001, LeadStatus.OFFER_SENT)
    assert first.status == repeated.status == LeadStatus.OFFER_SENT
    assert await _event_count(session_factory, lead_id) == event_count
    assert await _event_count(session_factory, lead_id, ContactEventType.MANAGER_ASSIGNED) == 1


async def test_board_noop_still_checks_manager_ownership(session_factory):
    lead_id = await create_lead(session_factory)
    crm = CRMService(session_factory)
    await crm.move_lead_toward(lead_id, 1001, LeadStatus.TAKEN)
    count = await _event_count(session_factory, lead_id)
    with pytest.raises(LeadAlreadyAssignedError):
        await crm.move_lead_toward(lead_id, 2002, LeadStatus.TAKEN)
    assert await _event_count(session_factory, lead_id) == count


@pytest.mark.parametrize("without_feedback", [False, True])
async def test_board_rejection_records_manual_decision(session_factory, without_feedback):
    lead_id = await create_lead(session_factory)
    if without_feedback:
        async with session_factory() as session:
            await session.execute(delete(AIFeedback).where(AIFeedback.lead_id == lead_id))
            lead = await session.get(Lead, lead_id)
            lead.status = LeadStatus.ANALYZING
            await session.commit()
    crm = CRMService(session_factory)
    await crm.move_lead_toward(lead_id, 1001, LeadStatus.NOT_LEAD)
    await crm.move_lead_toward(lead_id, 1001, LeadStatus.NOT_LEAD)
    async with session_factory() as session:
        feedback = await session.scalar(select(AIFeedback).where(AIFeedback.lead_id == lead_id))
        if not without_feedback:
            assert feedback.manager_is_lead is False
            assert feedback.actual_outcome == LeadStatus.NOT_LEAD.value
        event = await session.scalar(
            select(ContactEvent).where(
                ContactEvent.lead_id == lead_id,
                ContactEvent.event_type == ContactEventType.MANAGER_MARKED_NOT_LEAD,
            )
        )
        assert event.manager_telegram_id == 1001
        assert event.payload_json["via"] == "stage"
    assert await _event_count(session_factory, lead_id, ContactEventType.MANAGER_MARKED_NOT_LEAD) == 1


async def test_stage_confirms_existing_ai_rejection_once(session_factory):
    lead_id = await create_lead(session_factory)
    async with session_factory() as session:
        lead = await session.get(Lead, lead_id)
        lead.status = LeadStatus.NOT_LEAD
        await session.commit()
    crm = CRMService(session_factory)
    await crm.move_lead_toward(lead_id, 1001, LeadStatus.NOT_LEAD)
    await crm.move_lead_toward(lead_id, 1001, LeadStatus.NOT_LEAD)
    async with session_factory() as session:
        feedback = await session.scalar(select(AIFeedback).where(AIFeedback.lead_id == lead_id))
        assert feedback.manager_is_lead is False
        assert feedback.actual_outcome == LeadStatus.NOT_LEAD.value
    assert await _event_count(session_factory, lead_id, ContactEventType.MANAGER_MARKED_NOT_LEAD) == 1


async def test_reopen_retry_clears_rejected_outcome_without_duplicate_history(session_factory):
    lead_id = await create_lead(session_factory)
    workflow = LeadWorkflowService(session_factory, 70)
    await workflow.mark_not_lead(lead_id, 1001)
    crm = CRMService(session_factory)
    first = await crm.reopen_not_lead(lead_id, 1001)
    repeated = await crm.reopen_not_lead(lead_id, 1001)
    assert first.status == repeated.status == LeadStatus.TAKEN
    async with session_factory() as session:
        feedback = await session.scalar(select(AIFeedback).where(AIFeedback.lead_id == lead_id))
        contact = await session.get(Contact, first.contact_id)
        assert feedback.manager_is_lead is True
        assert feedback.actual_outcome is None
        assert contact.assigned_manager_telegram_id == 1001
    assert await _event_count(session_factory, lead_id, ContactEventType.LEAD_REOPENED) == 1


async def test_reopen_rejects_foreign_manager_without_reassignment(session_factory):
    lead_id = await create_lead(session_factory)
    workflow = LeadWorkflowService(session_factory, 70)
    await workflow.assign_manager(lead_id, 1001)
    await workflow.mark_not_lead(lead_id, 1001)
    with pytest.raises(LeadAlreadyAssignedError):
        await CRMService(session_factory).reopen_not_lead(lead_id, 2002)
    async with session_factory() as session:
        lead = await session.get(Lead, lead_id)
        contact = await session.get(Contact, lead.contact_id)
        assert lead.status == LeadStatus.NOT_LEAD
        assert lead.assigned_manager_telegram_id == contact.assigned_manager_telegram_id == 1001
    assert await _event_count(session_factory, lead_id, ContactEventType.LEAD_REOPENED) == 0


async def _pause_competing_lead_reads(monkeypatch, lead_id):
    """Make unlocked readers overlap; locked readers wait only for this short window."""
    original_get = AsyncSession.get
    both_read = asyncio.Event()
    read_count = 0

    async def paused_get(self, model, identifier, *args, **kwargs):
        nonlocal read_count
        value = await original_get(self, model, identifier, *args, **kwargs)
        if model is Lead and identifier == lead_id and not both_read.is_set():
            read_count += 1
            if read_count == 2:
                both_read.set()
            try:
                await asyncio.wait_for(both_read.wait(), timeout=0.1)
            except TimeoutError:
                both_read.set()
        return value

    monkeypatch.setattr(AsyncSession, "get", paused_get)


@pytest.mark.parametrize("manager_ids", [(1001, 2002), (1001, 1001)])
async def test_concurrent_board_assignment_has_one_owner_and_event(
    file_session_factory, monkeypatch, manager_ids
):
    lead_id = await create_lead(file_session_factory)
    await _pause_competing_lead_reads(monkeypatch, lead_id)
    crm = CRMService(file_session_factory)
    results = await asyncio.gather(
        *(crm.move_lead_toward(lead_id, manager_id, LeadStatus.TAKEN) for manager_id in manager_ids),
        return_exceptions=True,
    )
    if len(set(manager_ids)) > 1:
        assert sum(isinstance(item, Lead) for item in results) == 1
        assert sum(isinstance(item, LeadAlreadyAssignedError) for item in results) == 1
    else:
        assert all(isinstance(item, Lead) for item in results)
    async with file_session_factory() as session:
        lead = await session.get(Lead, lead_id)
        contact = await session.get(Contact, lead.contact_id)
        assert lead.assigned_manager_telegram_id == contact.assigned_manager_telegram_id
        assert lead.assigned_manager_telegram_id in manager_ids
    assert await _event_count(file_session_factory, lead_id, ContactEventType.MANAGER_ASSIGNED) == 1


async def _make_task(factory):
    lead_id = await create_lead(factory)
    async with factory() as session:
        lead = await session.get(Lead, lead_id)
        contact_id = lead.contact_id
    return lead_id, await CRMService(factory).schedule_contact(
        contact_id,
        1001,
        due_at=datetime.now(UTC) + timedelta(days=1),
        note="Follow up",
        lead_id=lead_id,
    )


async def test_cancelled_task_cannot_be_completed(session_factory):
    lead_id, task = await _make_task(session_factory)
    crm = CRMService(session_factory)
    await crm.cancel_task(task.id, 1001)
    with pytest.raises(LeadWorkflowError, match="Отменённую"):
        await crm.complete_task(task.id, 1001)
    async with session_factory() as session:
        stored = await session.get(ContactTask, task.id)
        assert stored.status == TaskStatus.CANCELLED
        assert stored.completed_at is None
    assert await _event_count(session_factory, lead_id, ContactEventType.NEXT_CONTACT_CANCELLED) == 1
    assert await _event_count(session_factory, lead_id, ContactEventType.NEXT_CONTACT_COMPLETED) == 0


async def test_completed_task_repeat_is_idempotent_and_cannot_cancel(session_factory):
    lead_id, task = await _make_task(session_factory)
    crm = CRMService(session_factory)
    first = await crm.complete_task(task.id, 1001)
    second = await crm.complete_task(task.id, 1001)
    assert first.status == second.status == TaskStatus.DONE
    with pytest.raises(LeadWorkflowError, match="Выполненную"):
        await crm.cancel_task(task.id, 1001)
    assert await _event_count(session_factory, lead_id, ContactEventType.NEXT_CONTACT_COMPLETED) == 1


@pytest.mark.parametrize("operation,event_type", [
    ("complete_task", ContactEventType.NEXT_CONTACT_COMPLETED),
    ("cancel_task", ContactEventType.NEXT_CONTACT_CANCELLED),
])
async def test_concurrent_task_retry_creates_one_history_event(
    file_session_factory, operation, event_type
):
    lead_id, task = await _make_task(file_session_factory)
    crm = CRMService(file_session_factory)
    await asyncio.gather(*(getattr(crm, operation)(task.id, 1001) for _ in range(3)))
    assert await _event_count(file_session_factory, lead_id, event_type) == 1


async def test_cancelled_task_complete_api_returns_conflict(session_factory):
    _, task = await _make_task(session_factory)
    crm = CRMService(session_factory)
    await crm.cancel_task(task.id, 1001)
    settings = Settings(_env_file=None, instagram_provider="replay", web_manager_id=1001)
    app = build_web_app(
        settings,
        WebQueryService(session_factory, 70),
        LeadWorkflowService(session_factory, 70),
        MonitorController(None),
        crm=crm,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(f"/api/tasks/{task.id}/complete", json={})
    assert response.status_code == 409
    assert "Отменённую" in response.json()["detail"]


def _crm_app(factory):
    return build_web_app(
        Settings(_env_file=None, instagram_provider="replay", web_manager_id=1001),
        WebQueryService(factory, 70),
        LeadWorkflowService(factory, 70),
        MonitorController(None),
        crm=CRMService(factory),
    )


async def test_concurrent_deal_create_api_is_idempotent(file_session_factory, monkeypatch):
    lead_id = await create_lead(file_session_factory)
    original_scalar = AsyncSession.scalar
    both_read = asyncio.Event()
    read_count = 0

    async def paused_empty_deal_read(self, statement, *args, **kwargs):
        nonlocal read_count
        value = await original_scalar(self, statement, *args, **kwargs)
        if "FROM deals" in str(statement) and value is None and not both_read.is_set():
            read_count += 1
            if read_count == 2:
                both_read.set()
            try:
                await asyncio.wait_for(both_read.wait(), timeout=0.1)
            except TimeoutError:
                both_read.set()
        return value

    monkeypatch.setattr(AsyncSession, "scalar", paused_empty_deal_read)
    app = _crm_app(file_session_factory)
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    ) as client:
        responses = await asyncio.gather(*(
            client.post(
                f"/api/leads/{lead_id}/deal",
                json={"product_name": "CORDA", "quantity": 2, "amount": "1000000"},
            )
            for _ in range(3)
        ))
    assert [response.status_code for response in responses] == [200, 200, 200]
    assert len({response.json()["deal_id"] for response in responses}) == 1
    async with file_session_factory() as session:
        deals = list(await session.scalars(select(Deal).where(Deal.lead_id == lead_id)))
        assert len(deals) == 1
        assert deals[0].product_name == "CORDA"
        assert deals[0].quantity == 2
        assert deals[0].amount == Decimal("1000000")
    assert await _event_count(file_session_factory, lead_id, ContactEventType.DEAL_CREATED) == 1


@pytest.mark.parametrize("closed_status", [LeadStatus.NOT_LEAD, LeadStatus.WON, LeadStatus.LOST])
@pytest.mark.parametrize("existing_deal", [False, True])
async def test_closed_lead_deal_api_conflict_preserves_history(
    session_factory, closed_status, existing_deal
):
    lead_id = await create_lead(session_factory)
    if existing_deal:
        await CRMService(session_factory).upsert_deal(
            lead_id, 1001, product_name="Original", quantity=1, amount=Decimal("500")
        )
    if closed_status == LeadStatus.NOT_LEAD:
        await LeadWorkflowService(session_factory, 70).mark_not_lead(lead_id, 1001)
    else:
        # Legacy/inconsistent data must not permit a new open deal on a closed lead.
        async with session_factory() as session:
            lead = await session.get(Lead, lead_id)
            lead.status = closed_status
            await session.commit()
    original_events = await _event_count(session_factory, lead_id)
    async with AsyncClient(transport=ASGITransport(app=_crm_app(session_factory)), base_url="http://test") as client:
        response = await client.post(
            f"/api/leads/{lead_id}/deal",
            json={"product_name": "Replacement", "quantity": 3, "amount": "1000"},
        )
    assert response.status_code == 409
    assert "закрытого лида" in response.json()["detail"]
    async with session_factory() as session:
        lead = await session.get(Lead, lead_id)
        assert lead.status == closed_status
        deal = await session.scalar(select(Deal).where(Deal.lead_id == lead_id))
        if existing_deal:
            assert deal.product_name == "Original"
            assert deal.quantity == 1
            assert deal.amount == Decimal("500")
        else:
            assert deal is None
    assert await _event_count(session_factory, lead_id) == original_events


@pytest.mark.parametrize("active_status", [LeadStatus.NEW, LeadStatus.TAKEN, LeadStatus.NEGOTIATION])
async def test_active_lead_deal_api_preserves_existing_stage_contract(session_factory, active_status):
    lead_id = await create_lead(session_factory)
    if active_status != LeadStatus.NEW:
        await CRMService(session_factory).move_lead_toward(lead_id, 1001, active_status)
    async with AsyncClient(transport=ASGITransport(app=_crm_app(session_factory)), base_url="http://test") as client:
        first = await client.post(
            f"/api/leads/{lead_id}/deal", json={"product_name": "CORDA", "quantity": 1}
        )
        updated = await client.post(
            f"/api/leads/{lead_id}/deal", json={"product_name": "CORDA", "quantity": 2}
        )
    assert first.status_code == updated.status_code == 200
    assert first.json()["deal_id"] == updated.json()["deal_id"]
    async with session_factory() as session:
        lead = await session.get(Lead, lead_id)
        deal = await session.get(Deal, first.json()["deal_id"])
        assert lead.status == active_status
        assert deal.quantity == 2
    assert await _event_count(session_factory, lead_id, ContactEventType.DEAL_CREATED) == 1


@pytest.mark.parametrize("payload", [{"amount": "not-a-number"}, {"quantity": "not-an-integer"}])
async def test_malformed_deal_values_remain_bad_request(session_factory, payload):
    lead_id = await create_lead(session_factory)
    original_events = await _event_count(session_factory, lead_id)
    async with AsyncClient(transport=ASGITransport(app=_crm_app(session_factory)), base_url="http://test") as client:
        response = await client.post(f"/api/leads/{lead_id}/deal", json=payload)
    assert response.status_code == 400
    async with session_factory() as session:
        assert await session.scalar(select(Deal).where(Deal.lead_id == lead_id)) is None
    assert await _event_count(session_factory, lead_id) == original_events
