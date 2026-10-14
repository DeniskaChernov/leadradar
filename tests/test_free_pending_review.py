import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.config import Settings
from app.db.models import AIRequest, AIRequestStatus, ContactEvent, ExternalUsage, Lead, LeadStatus
from app.services.ai_service import OpenAILeadAnalyzer
from app.services.lead_service import LeadService
from app.services.lead_workflow_service import LeadWorkflowService
from app.services.monitor_controller import MonitorController
from app.services.operational_control_service import OperationalControlService
from app.services.usage_service import ExternalUsageService, UsageSnapshot
from app.web.app import build_web_app
from app.web.queries import WebQueryService
from tests.test_pending_qualification_recovery import (
    BudgetBlockedAnalyzer,
    IdleMonitor,
    pending_signal,
)


async def history(factory):
    async with factory() as session:
        return [(e.id, e.event_type, e.payload_json) for e in await session.scalars(
            select(ContactEvent).order_by(ContactEvent.id))]


async def test_permanent_api_failure_does_not_block_free_rules(session_factory):
    analyzer = BudgetBlockedAnalyzer()
    service = LeadService(session_factory, analyzer, 70)
    pending = await pending_signal(session_factory, service, "narxi?", "permanent")
    async with session_factory() as session:
        request = AIRequest(lead_id=pending.lead_id, context_fingerprint="a" * 64,
                            model="test", status=AIRequestStatus.PERMANENT_FAILURE)
        session.add(request)
        await session.commit()
    assert await service.list_pending_lead_ids() == []
    before, calls = await history(session_factory), analyzer.calls
    recovered = await service.retry_pending_local()
    assert [item.lead_id for item in recovered] == [pending.lead_id]
    assert analyzer.calls == calls
    after = await history(session_factory)
    assert after[:len(before)] == before and len(after) > len(before)
    assert await service.retry_pending_local() == []
    assert await history(session_factory) == after
    async with session_factory() as session:
        assert (await session.get(AIRequest, request.id)).status == AIRequestStatus.PERMANENT_FAILURE
        assert (await session.get(Lead, pending.lead_id)).status == LeadStatus.NEW


@pytest.mark.parametrize("lease_seconds", [None, -60, 60])
async def test_local_review_waits_for_claimed_api_request(session_factory, lease_seconds):
    service = LeadService(session_factory, BudgetBlockedAnalyzer(), 70)
    pending = await pending_signal(session_factory, service, "narxi?", "claimed")
    async with session_factory() as session:
        request = AIRequest(lead_id=pending.lead_id, context_fingerprint="b" * 64,
                            model="test", status=AIRequestStatus.CLAIMED,
                            claim_expires_at=None if lease_seconds is None else
                            datetime.now(UTC) + timedelta(seconds=lease_seconds))
        session.add(request)
        await session.commit()
    before = await history(session_factory)
    assert await service.retry_pending_local() == []
    assert await history(session_factory) == before
    async with session_factory() as session:
        assert (await session.get(Lead, pending.lead_id)).status == LeadStatus.AI_PENDING
        request = await session.get(AIRequest, request.id)
        request.status = AIRequestStatus.RETRYABLE
        await session.commit()
    assert len(await service.retry_pending_local()) == 1


async def test_concurrent_local_reviews_only_commit_one_qualification(file_session_factory, monkeypatch):
    session_factory = file_session_factory
    service = LeadService(session_factory, BudgetBlockedAnalyzer(), 70)
    pending = await pending_signal(session_factory, service, "narxi?", "concurrent")
    before = await history(session_factory)
    original = service._build_context
    both_ready = asyncio.Event()
    arrivals = 0

    async def synchronized_context(session, comment_id):
        nonlocal arrivals
        context = await original(session, comment_id)
        arrivals += 1
        if arrivals == 2:
            both_ready.set()
        await asyncio.wait_for(both_ready.wait(), timeout=10)
        return context

    monkeypatch.setattr(service, "_build_context", synchronized_context)
    await asyncio.gather(service.retry_pending_local(), service.retry_pending_local())
    after = await history(session_factory)
    assert after[:len(before)] == before
    assert sum(event[1].value == "LEAD_SCORE_CHANGED" for event in after[len(before):]) == 1
    async with session_factory() as session:
        assert (await session.get(Lead, pending.lead_id)).status == LeadStatus.NEW


@pytest.mark.parametrize("claim_stage", ["after_selection", "before_final_write"])
async def test_free_review_does_not_overwrite_a_late_ai_claim(
    file_session_factory, monkeypatch, claim_stage,
):
    factory = file_session_factory
    service = LeadService(factory, BudgetBlockedAnalyzer(), 70)
    pending = await pending_signal(factory, service, "narxi?", "late-claim")
    before = await history(factory)

    async def acquire_claim():
        async with factory() as session:
            session.add(AIRequest(lead_id=pending.lead_id, context_fingerprint="c" * 64,
                                  model="test", status=AIRequestStatus.CLAIMED,
                                  claim_expires_at=datetime.now(UTC) + timedelta(seconds=60)))
            await session.commit()

    if claim_stage == "after_selection":
        original = service.list_pending_lead_ids

        async def claim_after_selection(*args, **kwargs):
            selected = await original(*args, **kwargs)
            await acquire_claim()
            return selected

        monkeypatch.setattr(service, "list_pending_lead_ids", claim_after_selection)
    else:
        async def claim_during_snapshot(_contact_id):
            await acquire_claim()
            return None

        service.change_detector = SimpleNamespace(snapshot=claim_during_snapshot)

    assert await service.retry_pending_local() == []
    assert await history(factory) == before
    async with factory() as session:
        lead = await session.get(Lead, pending.lead_id)
        assert lead.status == LeadStatus.AI_PENDING
        assert lead.ai_attempt_count == (1 if claim_stage == "after_selection" else 2)
        assert await session.scalar(select(func.count(AIRequest.id)).where(
            AIRequest.status == AIRequestStatus.CLAIMED)) == 1


async def make_app(factory, *, openai_allowed=False, analysis_pipeline=None):
    ops = OperationalControlService(factory)
    await ops.set_openai_live(openai_allowed)
    return build_web_app(
        Settings(_env_file=None, web_enabled=True, web_manager_id=1001,
                 openai_live_calls_enabled=openai_allowed, external_kill_switch=False,
                 external_live_unlock="ALLOW_EXTERNAL_CALLS" if openai_allowed else "",
                 openai_daily_request_limit=25,
                 openai_api_key="test-only" if openai_allowed else ""),
        WebQueryService(factory, hot_threshold=70), LeadWorkflowService(factory, 70),
        MonitorController(IdleMonitor()), ExternalUsageService(factory), ops_control=ops,
        analysis_pipeline=analysis_pipeline,
    )


async def test_free_endpoint_never_uses_ai_even_when_armed_and_keeps_ambiguity(session_factory, monkeypatch):
    service = LeadService(session_factory, BudgetBlockedAnalyzer(), 70)
    decidable = await pending_signal(session_factory, service, "narxi?", "price")
    ambiguous = await pending_signal(session_factory, service, "Непонятный комментарий", "ambiguous")
    ai = AsyncMock(side_effect=AssertionError("Free endpoint must not call AI"))
    monkeypatch.setattr(OpenAILeadAnalyzer, "analyze", ai)
    app = await make_app(session_factory, openai_allowed=True)
    before = await history(session_factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post("/api/leads/retry-pending-local", json={"limit": 100})
        after = await history(session_factory)
        second = await client.post("/api/leads/retry-pending-local", json={"limit": 100})
    assert first.status_code == second.status_code == 200
    assert first.json()["processed"] == 1 and first.json()["remaining"] == 1
    assert second.json()["processed"] == 0 and second.json()["remaining"] == 1
    assert not first.json()["openai_used"] and not first.json()["async"]
    ai.assert_not_awaited()
    assert after[:len(before)] == before and await history(session_factory) == after
    async with session_factory() as session:
        assert (await session.get(Lead, decidable.lead_id)).status == LeadStatus.NEW
        assert (await session.get(Lead, ambiguous.lead_id)).status == LeadStatus.AI_PENDING
        assert await session.scalar(select(func.count(ExternalUsage.id))) == 0


async def test_review_all_also_recovers_existing_pending_when_no_new_comments(session_factory):
    service = LeadService(session_factory, BudgetBlockedAnalyzer(), 70)
    pending = await pending_signal(session_factory, service, "narxi?", "existing")
    app = await make_app(session_factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        reply = await client.post("/api/signals/review-all", json={"limit": 100})
    assert reply.status_code == 200
    assert reply.json()["processed"] == reply.json()["local_recovered"] == 1
    async with session_factory() as session:
        assert (await session.get(Lead, pending.lead_id)).status == LeadStatus.NEW


@pytest.mark.parametrize("limit", [0, -1, 501, "bad", 1.5, True, None])
async def test_invalid_local_limit_is_rejected_without_work(session_factory, limit):
    service = LeadService(session_factory, BudgetBlockedAnalyzer(), 70)
    pending = await pending_signal(session_factory, service, "narxi?", "invalid")
    app = await make_app(session_factory)
    before = await history(session_factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        reply = await client.post("/api/leads/retry-pending-local", json={"limit": limit})
    assert reply.status_code == 400 and await history(session_factory) == before
    async with session_factory() as session:
        assert (await session.get(Lead, pending.lead_id)).status == LeadStatus.AI_PENDING


@pytest.mark.parametrize("endpoint", ["/api/signals/review-all", "/api/leads/retry-pending"])
@pytest.mark.parametrize("with_pipeline", [False, True])
async def test_exhausted_daily_budget_preserves_pending_without_ai_or_queue(
    session_factory, monkeypatch, endpoint, with_pipeline,
):
    service = LeadService(session_factory, BudgetBlockedAnalyzer(), 70)
    pending = await pending_signal(session_factory, service, "Непонятный комментарий", "budget")
    enqueue = AsyncMock(side_effect=AssertionError("Exhausted budget must not queue paid work"))
    pipeline = SimpleNamespace(enqueue_retry_batch=enqueue) if with_pipeline else None
    ai = AsyncMock(side_effect=AssertionError("Exhausted budget must not call AI"))
    monkeypatch.setattr(OpenAILeadAnalyzer, "analyze", ai)
    monkeypatch.setattr(ExternalUsageService, "snapshot", AsyncMock(
        return_value=UsageSnapshot("openai", 25, 25, 0)))
    app = await make_app(session_factory, openai_allowed=True, analysis_pipeline=pipeline)
    before = await history(session_factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        reply = await client.post(endpoint, json={"limit": 100})
    assert reply.status_code == 200
    body = reply.json()
    assert body["processed"] == 0 and body["openai_remaining"] == 0
    assert not body["openai_used"] and not body["async"]
    assert body.get("remaining_pending", body.get("still_pending")) == 1
    assert "лимит GPT исчерпан: 25/25" in body["message"]
    assert await history(session_factory) == before
    ai.assert_not_awaited()
    enqueue.assert_not_awaited()
    async with session_factory() as session:
        lead = await session.get(Lead, pending.lead_id)
        assert lead.status == LeadStatus.AI_PENDING and lead.ai_attempt_count == 1
        assert await session.scalar(select(func.count(ExternalUsage.id))) == 0


@pytest.mark.parametrize("endpoint", ["/api/signals/review-all", "/api/leads/retry-pending"])
@pytest.mark.parametrize("queued", [0, 2])
async def test_paid_queue_is_capped_by_remaining_daily_budget_and_reports_actual_work(
    session_factory, monkeypatch, endpoint, queued,
):
    service = LeadService(session_factory, BudgetBlockedAnalyzer(), 70)
    await pending_signal(session_factory, service, "Непонятный комментарий", "cap")
    enqueue = AsyncMock(return_value=queued)
    monkeypatch.setattr(ExternalUsageService, "snapshot", AsyncMock(
        return_value=UsageSnapshot("openai", 23, 25, 2)))
    app = await make_app(session_factory, openai_allowed=True,
                         analysis_pipeline=SimpleNamespace(enqueue_retry_batch=enqueue))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        reply = await client.post(endpoint, json={"limit": 10, "gpt_limit": 10})
    assert reply.status_code == 200
    body = reply.json()
    enqueue.assert_awaited_once_with(2, cooldown_seconds=0)
    assert body.get("gpt_queued", body.get("queued")) == queued
    assert body["openai_remaining"] == 2
    assert body["async"] == body["openai_used"] == bool(queued)
    if not queued:
        assert "идёт в фоне" not in body["message"]


async def test_retry_without_ai_recovers_rules_and_leaves_ambiguous_attempt_count_unchanged(
    session_factory, monkeypatch,
):
    service = LeadService(session_factory, BudgetBlockedAnalyzer(), 70)
    await pending_signal(session_factory, service, "narxi?", "disabled-price")
    pending = await pending_signal(session_factory, service, "Непонятный комментарий", "disabled")
    ai = AsyncMock(side_effect=AssertionError("Disabled AI must not be called"))
    monkeypatch.setattr(OpenAILeadAnalyzer, "analyze", ai)
    app = await make_app(session_factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        reply = await client.post("/api/leads/retry-pending", json={"limit": 10})
    assert reply.status_code == 200
    assert reply.json()["processed"] == reply.json()["still_pending"] == 1
    assert not reply.json()["openai_used"]
    ai.assert_not_awaited()
    async with session_factory() as session:
        lead = await session.get(Lead, pending.lead_id)
        assert lead.status == LeadStatus.AI_PENDING and lead.ai_attempt_count == 1
