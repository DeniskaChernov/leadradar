"""A score refresh after a commit cannot turn success into a false failure."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.db.models import ContactEvent, Lead
from app.services.lead_workflow_service import LeadWorkflowError
from tests.test_hot_backend_reliability import _history, _service
from tests.test_hot_outreach import _make_hot_lead


async def test_sent_repeat_remains_idempotent_after_score_drop(session_factory):
    lead_id = await _make_hot_lead(session_factory)
    service = _service(session_factory)
    original = await service.mark_sent(lead_id, 1001, message="Отправленный текст")
    async with session_factory() as session:
        lead = await session.get(Lead, lead_id)
        lead.lead_score = 10
        await session.commit()
    before = await _history(session_factory, lead_id)

    repeated = await service.mark_sent(lead_id, 1001, message="Отправленный текст")

    assert repeated["draft"] == original["draft"] and repeated["already_sent"]
    assert not any(repeated[key] for key in ("can_prepare", "can_save_draft", "can_mark_sent"))
    assert await service.detail(lead_id) is None
    assert await service.queue_position(lead_id) is None
    assert await _history(session_factory, lead_id) == before
    with pytest.raises(LeadWorkflowError, match="нельзя менять"):
        await service.mark_sent(lead_id, 1001, message="Другой текст")
    with pytest.raises(LeadWorkflowError, match="другому менеджеру"):
        await service.mark_sent(lead_id, 2002)


@pytest.mark.parametrize("operation", ["save", "prepare", "sent"])
async def test_score_drop_after_commit_returns_saved_result(session_factory, monkeypatch, operation):
    lead_id = await _make_hot_lead(session_factory)
    composer = SimpleNamespace(compose=AsyncMock(return_value="AI текст"))
    service = _service(session_factory, composer=composer)
    original_detail = service.detail
    applied = False

    async def refresh_score_before_result(*args, **kwargs):
        nonlocal applied
        async with session_factory() as session:
            lead = await session.get(Lead, lead_id)
            draft = (lead.analysis_details or {}).get("hot_outreach")
            if draft and (operation != "sent" or draft.get("sent_at")) and not applied:
                applied = True
                lead.lead_score = 10
                await session.commit()
        return await original_detail(*args, **kwargs)

    monkeypatch.setattr(service, "detail", refresh_score_before_result)
    if operation == "save":
        result = await service.save_draft(lead_id, 1001, "Ручной текст")
    elif operation == "prepare":
        result = await service.prepare(lead_id, 1001)
    else:
        result = await service.mark_sent(lead_id, 1001, message="Отправленный текст")

    assert applied and result["score"] == 10 and result["draft"]["message"]
    assert not any(result[key] for key in ("can_prepare", "can_save_draft", "can_mark_sent"))
    assert result["already_sent"] == (operation == "sent")
    async with session_factory() as session:
        events = list(await session.scalars(select(ContactEvent).where(ContactEvent.lead_id == lead_id)))
        expected_kind = {
            "save": "hot_outreach_draft_saved",
            "prepare": "hot_outreach_prepared",
            "sent": "hot_outreach_sent",
        }[operation]
        assert sum(event.payload_json.get("kind") == expected_kind for event in events) == 1
