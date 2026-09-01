"""Persistent agent chat, write tools, file allowlist."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.services.agent_chat_orchestrator import AgentChatOrchestrator
from app.services.crm_service import CRMService
from app.services.lead_workflow_service import LeadWorkflowService
from app.services.monitor_controller import MonitorController
from app.services.project_file_service import ProjectFileService
from app.web.app import build_web_app
from app.web.queries import WebQueryService


@pytest.mark.asyncio
async def test_agent_chat_persists_session_and_messages(session_factory):
    orchestrator = AgentChatOrchestrator(session_factory, hot_threshold=70)
    first = await orchestrator.chat_turn(1001, "покажи лиды", session_id=None)
    second = await orchestrator.chat_turn(
        1001,
        "покажи hot лиды",
        session_id=first.session_id,
    )
    messages = await orchestrator.chat.list_messages(first.session_id)
    assert first.session_id == second.session_id
    assert len(messages) >= 4
    assert messages[0].role == "user"
    assert messages[1].role == "assistant"


@pytest.mark.asyncio
async def test_competitor_manage_write_requires_approval(session_factory):
    orchestrator = AgentChatOrchestrator(session_factory, hot_threshold=70)
    turn = await orchestrator.chat_turn(
        1001,
        "добавь конкурента @pilot.test.shop tier a",
    )
    assert turn.pending_action is not None
    assert turn.pending_action["tool_name"] == "competitor.manage"
    approved = await orchestrator.approve_pending(
        turn.pending_action["message_id"],
        manager_telegram_id=1001,
    )
    assert approved["ok"] is True
    assert approved["tool_name"] == "competitor.manage"


def test_project_file_allowlist_blocks_traversal(tmp_path, monkeypatch):
    service = ProjectFileService()
    monkeypatch.setattr(
        "app.services.project_file_service.PROJECT_ROOT",
        tmp_path,
    )
    (tmp_path / "exports").mkdir()
    result = service.write_file("exports/note.txt", "hello")
    assert result.relative_path == "exports/note.txt"
    with pytest.raises(ValueError, match=r"allowlist|Недопустимый"):
        service.write_file("../secret.txt", "nope")


def _agent_app(session_factory):
    settings = Settings(
        _env_file=None,
        web_enabled=True,
        instagram_provider="replay",
        web_manager_id=1001,
    )
    return build_web_app(
        settings,
        WebQueryService(session_factory, hot_threshold=70),
        LeadWorkflowService(session_factory, hot_threshold=70),
        MonitorController(None),  # type: ignore[arg-type]
        crm=CRMService(session_factory),
    )


@pytest.mark.asyncio
async def test_agent_approve_rejects_invalid_message_id(session_factory):
    app = _agent_app(session_factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/agent/approve", json={"message_id": "abc"})
    assert response.status_code == 400
    assert "message_id" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_agent_chat_rejects_invalid_session_id(session_factory):
    app = _agent_app(session_factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/agent/chat",
            json={"query": "покажи лиды", "session_id": "bad"},
        )
    assert response.status_code == 400
    assert "session_id" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_agent_page_renders(session_factory):
    app = _agent_app(session_factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/agent")
    assert response.status_code == 200
    assert "data-agent-chat-root" in response.text
    assert "agent-hero" in response.text
    assert "data-agent-typing" in response.text
