"""Enrichment cannot replace a manager's committed qualification decision."""

import asyncio
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AIFeedback,
    ContactEvent,
    ContactEventType,
    Deal,
    DealSaleSnapshot,
    DealStatus,
    Lead,
    LeadStatus,
)
from app.services.ai_service import AIAnalysisError
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
from tests.test_lead_workflow import create_lead


class RejectAnalyzer(StaticAnalyzer):
    async def analyze(self, context):
        analysis = await super().analyze(context)
        return analysis.model_copy(update={"is_lead": False, "lead_score": 10})


@pytest.mark.parametrize("via_stage", [False, True])
async def test_reanalysis_preserves_manual_rejection(session_factory, via_stage):
    lead_id = await create_lead(session_factory)
    if via_stage:
        await CRMService(session_factory).move_lead(lead_id, 1001, LeadStatus.NOT_LEAD)
    else:
        await LeadWorkflowService(session_factory, 70).mark_not_lead(lead_id, 1001)

    result = await LeadService(session_factory, StaticAnalyzer(), 70).analyze_lead(lead_id)

    assert result.status == LeadStatus.NOT_LEAD and not result.is_hot
    async with session_factory() as session:
        feedback = await session.scalar(select(AIFeedback).where(AIFeedback.lead_id == lead_id))
        assert feedback.manager_is_lead is False
        assert feedback.actual_outcome == LeadStatus.NOT_LEAD.value
        assert await session.scalar(
            select(func.count(ContactEvent.id)).where(
                ContactEvent.lead_id == lead_id,
                ContactEvent.event_type == ContactEventType.MANAGER_MARKED_NOT_LEAD,
            )
        ) == 1


async def test_manual_rejection_during_first_analysis_survives_result(file_session_factory):
    signal = await ContactService(file_session_factory).persist_signal(make_post(), make_comment())
    started, release = asyncio.Event(), asyncio.Event()

    class DelayedAnalyzer(StaticAnalyzer):
        async def analyze(self, context):
            started.set()
            await release.wait()
            return await super().analyze(context)

    service = LeadService(file_session_factory, DelayedAnalyzer(), 70)
    pending = await service.ensure_analyzing(signal)
    analysis = asyncio.create_task(service.analyze_lead(pending.lead_id))
    await asyncio.wait_for(started.wait(), 2)
    try:
        await LeadWorkflowService(file_session_factory, 70).mark_not_lead(pending.lead_id, 1001)
    finally:
        release.set()
    result = await analysis

    assert result.status == LeadStatus.NOT_LEAD and not result.is_hot
    async with file_session_factory() as session:
        feedback = await session.scalar(select(AIFeedback).where(AIFeedback.lead_id == result.lead_id))
        assert feedback.manager_is_lead is False
        assert feedback.actual_outcome == LeadStatus.NOT_LEAD.value


async def test_negative_reanalysis_classifies_unassigned_new_lead(session_factory):
    lead_id = await create_lead(session_factory)
    result = await LeadService(session_factory, RejectAnalyzer(), 70).analyze_lead(lead_id)
    assert result.status == LeadStatus.NOT_LEAD and not result.is_hot


async def test_positive_reanalysis_can_reopen_automatic_rejection(session_factory):
    signal = await ContactService(session_factory).persist_signal(make_post(), make_comment())
    rejected = await LeadService(session_factory, RejectAnalyzer(), 70).process_signal(signal)
    assert rejected.status == LeadStatus.NOT_LEAD
    result = await LeadService(session_factory, StaticAnalyzer(), 70).analyze_lead(rejected.lead_id)
    assert result.status == LeadStatus.NEW and result.is_hot


async def test_explicit_reopen_clears_rejection_before_reanalysis(session_factory):
    lead_id = await create_lead(session_factory)
    await LeadWorkflowService(session_factory, 70).mark_not_lead(lead_id, 1001)
    await CRMService(session_factory).reopen_not_lead(lead_id, 1001)
    result = await LeadService(session_factory, RejectAnalyzer(), 70).analyze_lead(lead_id)
    assert result.status == LeadStatus.TAKEN
    async with session_factory() as session:
        feedback = await session.scalar(select(AIFeedback).where(AIFeedback.lead_id == lead_id))
        assert feedback.manager_is_lead is True and feedback.actual_outcome is None


async def test_explicit_rejection_of_automatic_not_lead_is_persisted_once(session_factory):
    signal = await ContactService(session_factory).persist_signal(make_post(), make_comment())
    rejected = await LeadService(session_factory, RejectAnalyzer(), 70).process_signal(signal)
    workflow = LeadWorkflowService(session_factory, 70)
    await workflow.mark_not_lead(rejected.lead_id, 1001)
    await workflow.mark_not_lead(rejected.lead_id, 1001)
    result = await LeadService(session_factory, StaticAnalyzer(), 70).analyze_lead(rejected.lead_id)
    assert result.status == LeadStatus.NOT_LEAD
    async with session_factory() as session:
        assert await session.scalar(
            select(func.count(ContactEvent.id)).where(
                ContactEvent.lead_id == rejected.lead_id,
                ContactEvent.event_type == ContactEventType.MANAGER_MARKED_NOT_LEAD,
            )
        ) == 1


async def test_rejected_lead_noop_still_enforces_owner(session_factory):
    lead_id = await create_lead(session_factory)
    workflow = LeadWorkflowService(session_factory, 70)
    await workflow.assign_manager(lead_id, 1001)
    await workflow.mark_not_lead(lead_id, 1001)
    with pytest.raises(LeadAlreadyAssignedError):
        await workflow.mark_not_lead(lead_id, 2002)


@pytest.mark.parametrize("status", [LeadStatus.TAKEN, LeadStatus.CONTACTED, LeadStatus.WON])
async def test_negative_analysis_preserves_manager_workflow(session_factory, status):
    lead_id = await create_lead(session_factory)
    async with session_factory() as session:
        lead = await session.get(Lead, lead_id)
        lead.status = status
        lead.assigned_manager_telegram_id = 1001
        await session.commit()
    result = await LeadService(session_factory, RejectAnalyzer(), 70).analyze_lead(lead_id)
    assert result.status == status


@pytest.mark.parametrize("operation", ["win", "lose"])
async def test_existing_open_deal_cannot_override_manual_rejection(session_factory, operation):
    lead_id = await create_lead(session_factory)
    deal = await CRMService(session_factory).upsert_deal(lead_id, 1001, product_name="Original")
    workflow = LeadWorkflowService(session_factory, 70)
    await workflow.mark_not_lead(lead_id, 1001)
    async with session_factory() as session:
        history_count = await session.scalar(select(func.count(ContactEvent.id)))
    with pytest.raises(LeadWorkflowError):
        if operation == "win":
            await workflow.win_deal(deal.id, 1001, product_name="Original", amount=Decimal(100), quantity=1)
        else:
            await workflow.lose_deal(deal.id, 1001, reason="Cancelled")
    async with session_factory() as session:
        assert (await session.get(Lead, lead_id)).status == LeadStatus.NOT_LEAD
        assert (await session.get(Deal, deal.id)).status == DealStatus.NEW
        assert await session.scalar(select(func.count(ContactEvent.id))) == history_count
        assert await session.scalar(select(func.count(DealSaleSnapshot.id))) == 0


async def test_concurrent_win_retry_preserves_one_sale_and_event(file_session_factory):
    lead_id = await create_lead(file_session_factory)
    deal = await CRMService(file_session_factory).upsert_deal(lead_id, 1001, product_name="Original")
    workflow = LeadWorkflowService(file_session_factory, 70)
    results = await asyncio.gather(*(
        workflow.win_deal(deal.id, 1001, product_name="Original", amount=Decimal(100), quantity=1)
        for _ in range(3)
    ))
    assert all(result.status == DealStatus.WON for result in results)
    async with file_session_factory() as session:
        assert await session.scalar(select(func.count(DealSaleSnapshot.id))) == 1
        assert await session.scalar(select(func.count(ContactEvent.id)).where(
            ContactEvent.event_type == ContactEventType.DEAL_WON,
        )) == 1


@pytest.mark.parametrize("decision", [LeadStatus.NOT_LEAD, LeadStatus.TAKEN])
async def test_failed_analysis_cannot_overwrite_concurrent_manager_decision(
    file_session_factory, monkeypatch, decision
):
    signal = await ContactService(file_session_factory).persist_signal(make_post(), make_comment())

    class FailingAnalyzer:
        async def analyze(self, _context):
            raise AIAnalysisError("Temporary analyzer failure")

    service = LeadService(file_session_factory, FailingAnalyzer(), 70)
    pending = await service.ensure_analyzing(signal)
    error_read, release = asyncio.Event(), asyncio.Event()
    original_get = AsyncSession.get
    reads = 0

    async def pause_error_read(session, entity, *args, **kwargs):
        nonlocal reads
        value = await original_get(session, entity, *args, **kwargs)
        if entity is Lead and asyncio.current_task().get_name() == "analysis_failure_race":
            reads += 1
            if reads == 2:
                error_read.set()
                await release.wait()
        return value

    monkeypatch.setattr(AsyncSession, "get", pause_error_read)
    analysis = asyncio.create_task(service.analyze_lead(pending.lead_id), name="analysis_failure_race")
    await asyncio.wait_for(error_read.wait(), 2)
    workflow = LeadWorkflowService(file_session_factory, 70)
    action = workflow.mark_not_lead if decision == LeadStatus.NOT_LEAD else workflow.assign_manager
    manager = asyncio.create_task(action(pending.lead_id, 1001))
    try:
        # Without the final write lock the manager commits here and the stale
        # error handler subsequently replaces that decision with AI_PENDING.
        await asyncio.wait_for(asyncio.shield(manager), 0.15)
    except TimeoutError:
        pass
    finally:
        release.set()
    await asyncio.gather(analysis, manager)
    async with file_session_factory() as session:
        lead = await session.get(Lead, pending.lead_id)
        assert lead.status == decision
        event_type = (ContactEventType.MANAGER_MARKED_NOT_LEAD
                      if decision == LeadStatus.NOT_LEAD else ContactEventType.MANAGER_ASSIGNED)
        assert await session.scalar(select(func.count(ContactEvent.id)).where(
            ContactEvent.lead_id == lead.id, ContactEvent.event_type == event_type,
        )) == 1
