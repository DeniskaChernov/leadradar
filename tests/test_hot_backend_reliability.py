"""HOT writes stay idempotent and cannot reopen history or overwrite manager edits."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.db.models import (
    Comment,
    Contact,
    ContactEvent,
    ContactEventType,
    Lead,
    LeadStatus,
    Vertical,
)
from app.db.repositories.events import ContactEventRepository
from app.services.crm_service import CRMService
from app.services.hot_outreach_service import HotOutreachService
from app.services.lead_service import LeadService
from app.services.lead_workflow_service import LeadWorkflowError, LeadWorkflowService
from app.services.product_catalog_service import ProductCatalogService
from tests.test_hot_outreach import _make_hot_lead
from tests.test_lead_service import StaticAnalyzer
from tests.test_openings_and_hot_pagination import _many_hot


def _service(factory, *, composer=None):
    return HotOutreachService(
        factory,
        hot_threshold=70,
        workflow=LeadWorkflowService(factory, 70),
        crm=CRMService(factory),
        catalog=ProductCatalogService(factory),
        composer=composer,
    )


async def _history(factory, lead_id):
    async with factory() as session:
        events = list(
            await session.scalars(
                select(ContactEvent)
                .where(ContactEvent.lead_id == lead_id)
                .order_by(ContactEvent.id)
            )
        )
        return [(event.id, event.event_type, event.payload_json) for event in events]


@pytest.mark.parametrize("message", [None, "Ручной текст", " Ручной текст "])
async def test_sent_repeat_keeps_timestamp_message_and_history(session_factory, message):
    lead_id = await _make_hot_lead(session_factory)
    service = _service(session_factory)
    sent = await service.mark_sent(lead_id, 1001, message="Ручной текст")
    before = await _history(session_factory, lead_id)

    repeated = await service.mark_sent(lead_id, 1001, message=message)

    assert repeated["status"] == LeadStatus.OFFER_SENT.value
    assert repeated["draft"] == sent["draft"]
    assert repeated["next_lead_id"] is None
    assert not repeated["can_mark_sent"]
    assert await _history(session_factory, lead_id) == before


async def test_sent_repeat_with_changed_text_does_not_rewrite_history(session_factory):
    lead_id = await _make_hot_lead(session_factory)
    service = _service(session_factory)
    original = await service.mark_sent(lead_id, 1001, message="Отправленный текст")
    before = await _history(session_factory, lead_id)

    with pytest.raises(LeadWorkflowError, match="нельзя менять"):
        await service.mark_sent(lead_id, 1001, message="Иной текст")

    assert (await service.detail(lead_id))["draft"] == original["draft"]
    assert await _history(session_factory, lead_id) == before


async def test_sent_event_failure_rolls_back_stages_and_allows_clean_retry(
    file_session_factory, monkeypatch
):
    lead_id = await _make_hot_lead(file_session_factory)
    service = _service(file_session_factory)
    original = await service.save_draft(lead_id, 1001, "Ручной текст")
    before = await _history(file_session_factory, lead_id)
    add_event = ContactEventRepository.add

    async def fail_sent_event(repository, *args, **kwargs):
        if (kwargs.get("payload") or {}).get("kind") == "hot_outreach_sent":
            raise RuntimeError("simulated storage failure after CRM transitions")
        return await add_event(repository, *args, **kwargs)

    monkeypatch.setattr(ContactEventRepository, "add", fail_sent_event)
    with pytest.raises(RuntimeError, match="simulated storage failure"):
        await service.mark_sent(lead_id, 1001)

    detail = await service.detail(lead_id)
    assert detail["status"] == LeadStatus.TAKEN.value
    assert detail["draft"] == original["draft"] and not detail["already_sent"]
    assert await _history(file_session_factory, lead_id) == before
    async with file_session_factory() as session:
        lead = await session.get(Lead, lead_id)
        contact = await session.get(Contact, lead.contact_id)
        assert contact.last_contacted_at is None and lead.outreach_claim_token is None

    monkeypatch.setattr(ContactEventRepository, "add", add_event)
    sent = await service.mark_sent(lead_id, 1001)
    assert sent["status"] == LeadStatus.OFFER_SENT.value and sent["already_sent"]
    after = await _history(file_session_factory, lead_id)
    assert after[: len(before)] == before
    assert sum(kind == ContactEventType.CONTACTED for _, kind, _ in after) == 1
    assert sum(kind == ContactEventType.OFFER_SENT for _, kind, _ in after) == 1
    assert sum(payload.get("kind") == "hot_outreach_sent" for _, _, payload in after) == 1
    await service.mark_sent(lead_id, 1001, message="Ручной текст")
    assert await _history(file_session_factory, lead_id) == after


@pytest.mark.parametrize("force", [False, True])
async def test_prepare_sent_lead_never_calls_composer(session_factory, force):
    lead_id = await _make_hot_lead(session_factory)
    composer = SimpleNamespace(compose=AsyncMock(return_value="Новый AI текст"))
    service = _service(session_factory, composer=composer)
    original = await service.mark_sent(lead_id, 1001, message="Отправленный текст")
    before = await _history(session_factory, lead_id)

    with pytest.raises(LeadWorkflowError, match="отправленное"):
        await service.prepare(lead_id, 1001, force=force)

    composer.compose.assert_not_awaited()
    detail = await service.detail(lead_id)
    assert detail["draft"] == original["draft"]
    assert not detail["can_save_draft"] and not detail["can_prepare"]
    assert await _history(session_factory, lead_id) == before


@pytest.mark.parametrize(
    "status",
    [
        LeadStatus.WON,
        LeadStatus.LOST,
        LeadStatus.NOT_LEAD,
        LeadStatus.NEGOTIATION,
        LeadStatus.OFFER_SENT,
    ],
)
async def test_closed_or_advanced_stage_rejects_hot_writes(session_factory, status):
    lead_id = await _make_hot_lead(session_factory)
    async with session_factory() as session:
        lead = await session.get(Lead, lead_id)
        lead.status = status
        await session.commit()
    composer = SimpleNamespace(compose=AsyncMock(return_value="AI текст"))
    service = _service(session_factory, composer=composer)
    before = await _history(session_factory, lead_id)

    for operation in (
        lambda: service.prepare(lead_id, 1001),
        lambda: service.save_draft(lead_id, 1001, "Текст"),
        lambda: service.mark_sent(lead_id, 1001, message="Текст"),
    ):
        with pytest.raises(LeadWorkflowError, match="стадии"):
            await operation()

    composer.compose.assert_not_awaited()
    detail = await service.detail(lead_id)
    assert detail["status"] == status.value and detail["draft"] is None
    assert (
        not detail["can_save_draft"] and not detail["can_prepare"] and not detail["can_mark_sent"]
    )
    assert await _history(session_factory, lead_id) == before


async def test_existing_draft_is_reused_with_composer_disabled(session_factory):
    lead_id = await _make_hot_lead(session_factory)
    service = _service(session_factory)
    original = await service.save_draft(lead_id, 1001, "Ручной текст")
    before = await _history(session_factory, lead_id)

    cached = await service.prepare(lead_id, 1001)
    duplicate = await service.save_draft(lead_id, 1001, " Ручной текст ")

    assert cached["draft"] == original["draft"] == duplicate["draft"]
    assert await _history(session_factory, lead_id) == before


async def test_cached_draft_reuse_honors_disabled_generation_gate(session_factory):
    lead_id = await _make_hot_lead(session_factory)
    composer = SimpleNamespace(compose=AsyncMock(return_value="AI текст"))
    service = _service(session_factory, composer=composer)
    original = await service.save_draft(lead_id, 1001, "Ручной текст")
    before = await _history(session_factory, lead_id)

    cached = await service.prepare(lead_id, 1001, allow_generation=False)
    assert cached["draft"] == original["draft"]
    with pytest.raises(LeadWorkflowError, match="OpenAI выключен"):
        await service.prepare(lead_id, 1001, force=True, allow_generation=False)
    composer.compose.assert_not_awaited()
    assert await _history(session_factory, lead_id) == before


async def test_disabled_generation_gate_does_not_assign_an_untouched_lead(session_factory):
    lead_id = await _make_hot_lead(session_factory)
    composer = SimpleNamespace(compose=AsyncMock(return_value="AI текст"))
    service = _service(session_factory, composer=composer)
    before = await _history(session_factory, lead_id)

    with pytest.raises(LeadWorkflowError, match="OpenAI выключен"):
        await service.prepare(lead_id, 1001, allow_generation=False)

    composer.compose.assert_not_awaited()
    async with session_factory() as session:
        lead = await session.get(Lead, lead_id)
        assert lead.status == LeadStatus.NEW and lead.assigned_manager_telegram_id is None
    assert await _history(session_factory, lead_id) == before


async def test_non_hot_lead_is_not_assigned_by_prepare(session_factory):
    lead_id = await _make_hot_lead(session_factory)
    async with session_factory() as session:
        lead = await session.get(Lead, lead_id)
        lead.lead_score = 25
        await session.commit()
    composer = SimpleNamespace(compose=AsyncMock(return_value="AI текст"))
    service = _service(session_factory, composer=composer)
    before = await _history(session_factory, lead_id)

    with pytest.raises(LeadWorkflowError, match="HOT-лид"):
        await service.prepare(lead_id, 1001)

    composer.compose.assert_not_awaited()
    async with session_factory() as session:
        lead = await session.get(Lead, lead_id)
        assert lead.status == LeadStatus.NEW and lead.assigned_manager_telegram_id is None
    assert await _history(session_factory, lead_id) == before


async def test_manual_edit_or_sent_cannot_race_active_ai_prepare(file_session_factory):
    lead_id = await _make_hot_lead(file_session_factory)
    started, release = asyncio.Event(), asyncio.Event()

    async def compose(_context):
        started.set()
        await release.wait()
        return "Подготовленный AI текст"

    service = _service(file_session_factory, composer=SimpleNamespace(compose=compose))
    task = asyncio.create_task(service.prepare(lead_id, 1001))
    try:
        await asyncio.wait_for(started.wait(), timeout=10)
        for operation in (
            lambda: service.save_draft(lead_id, 1001, "Конкурирующий ручной текст"),
            lambda: service.mark_sent(lead_id, 1001, message="Конкурирующий ручной текст"),
        ):
            with pytest.raises(LeadWorkflowError, match="обрабатывается"):
                await operation()
    finally:
        release.set()
        await task

    # The rejected manager edit is safe to retry after the explicit busy response.
    saved = await service.save_draft(lead_id, 1001, "Сохранённая ручная правка")
    assert saved["draft"]["message"] == "Сохранённая ручная правка"
    assert (await service.detail(lead_id))["draft"]["message"] == "Сохранённая ручная правка"


async def test_ai_result_cannot_edit_lead_closed_during_request(file_session_factory):
    lead_id = await _make_hot_lead(file_session_factory)
    started, release = asyncio.Event(), asyncio.Event()

    async def compose(_context):
        started.set()
        await release.wait()
        return "AI текст для уже закрытого лида"

    service = _service(file_session_factory, composer=SimpleNamespace(compose=compose))
    task = asyncio.create_task(service.prepare(lead_id, 1001))
    try:
        await asyncio.wait_for(started.wait(), timeout=10)
        async with file_session_factory() as session:
            lead = await session.get(Lead, lead_id)
            lead.status = LeadStatus.WON
            await session.commit()
        before = await _history(file_session_factory, lead_id)
    finally:
        release.set()
    with pytest.raises(LeadWorkflowError, match="устарела"):
        await task
    detail = await service.detail(lead_id)
    assert detail["status"] == "WON" and detail["draft"] is None
    assert await _history(file_session_factory, lead_id) == before


@pytest.mark.parametrize("sent", [False, True])
async def test_reanalysis_preserves_existing_hot_draft_and_sent_marker(file_session_factory, sent):
    lead_id = await _make_hot_lead(file_session_factory)
    service = _service(file_session_factory)
    original = await service.save_draft(lead_id, 1001, "Сохранённый текст менеджера")
    if sent:
        original = await service.mark_sent(lead_id, 1001)
    before = await _history(file_session_factory, lead_id)

    await LeadService(file_session_factory, StaticAnalyzer(), hot_threshold=70).analyze_lead(lead_id)

    detail = await service.detail(lead_id)
    assert detail["draft"] == original["draft"] and detail["already_sent"] == sent
    assert detail["status"] == original["status"]
    assert (await _history(file_session_factory, lead_id))[: len(before)] == before
    if sent:
        repeated = await service.mark_sent(lead_id, 1001, message=original["draft"]["message"])
        assert repeated["draft"] == original["draft"]


@pytest.mark.parametrize("sent", [False, True])
async def test_delayed_analysis_preserves_hot_action_during_external_wait(file_session_factory, sent):
    lead_id = await _make_hot_lead(file_session_factory)
    service = _service(file_session_factory)
    started, release = asyncio.Event(), asyncio.Event()

    class DelayedAnalyzer(StaticAnalyzer):
        async def analyze(self, context):
            started.set()
            await release.wait()
            return await super().analyze(context)

    analyzer = LeadService(file_session_factory, DelayedAnalyzer(), hot_threshold=70)
    task = asyncio.create_task(analyzer.analyze_lead(lead_id))
    try:
        await asyncio.wait_for(started.wait(), timeout=10)
        original = await service.save_draft(lead_id, 1001, "Текст, сохранённый пока работает AI")
        if sent:
            original = await service.mark_sent(lead_id, 1001)
        before = await _history(file_session_factory, lead_id)
    finally:
        release.set()
        await task

    detail = await service.detail(lead_id)
    assert detail["draft"] == original["draft"] and detail["already_sent"] == sent
    assert detail["status"] == original["status"]
    assert (await _history(file_session_factory, lead_id))[: len(before)] == before


async def test_queue_position_matches_all_filters_and_stable_order(session_factory):
    ids = await _many_hot(session_factory, count=85)
    service = _service(session_factory)
    assert await service.queue_position(ids[-1], vertical="FURNITURE") == 0
    assert await service.queue_position(ids[0], vertical="FURNITURE") == 84
    async with session_factory() as session:
        (await session.get(Lead, ids[0])).vertical = Vertical.ARTIFICIAL_RATTAN
        (await session.get(Lead, ids[1])).status = LeadStatus.WON
        old = await session.get(Lead, ids[2])
        (await session.get(Comment, old.comment_id)).created_at_platform = datetime.now(
            UTC
        ) - timedelta(days=31)
        await session.commit()

    assert await service.queue_position(ids[0], vertical="FURNITURE") is None
    assert await service.queue_position(ids[0], vertical="ARTIFICIAL_RATTAN") == 0
    assert await service.queue_position(ids[1]) is None
    assert await service.queue_position(ids[2]) is None
    queue = await service.queue(limit=200)
    for position, item in enumerate(queue):
        assert await service.queue_position(item["lead_id"]) == position
