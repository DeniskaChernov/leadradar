"""Integration tests for Phase 8 system/agent/export UI."""

from __future__ import annotations

from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.services.audience_service import AudienceEngine
from app.services.crm_service import CRMService
from app.services.lead_workflow_service import LeadWorkflowService
from app.services.monitor_controller import MonitorController
from app.web.app import build_web_app
from app.web.queries import WebQueryService
from tests.test_lead_workflow import create_lead


async def test_system_page_renders_agent_and_export_workspaces(session_factory):
    await AudienceEngine(session_factory, hot_threshold=70).sync_segments()
    settings = Settings(_env_file=None, web_enabled=True, instagram_provider="replay", web_manager_id=1001)
    app = build_web_app(
        settings,
        WebQueryService(session_factory, hot_threshold=70),
        LeadWorkflowService(session_factory, hot_threshold=70),
        MonitorController(None),  # type: ignore[arg-type]
        crm=CRMService(session_factory),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/system")
        agent = await client.post(
            "/api/agent/query",
            json={"query": "Покажи лиды"},
        )

    assert response.status_code == 200
    assert "GROUNDED AGENT · OFFLINE" in response.text
    assert "Export recipes preview" in response.text
    assert "b2b_horeca_wholesale" in response.text
    assert agent.status_code == 200
    assert agent.json()["grounded"] is True


async def test_lead_detail_renders_grounded_agent_panel(session_factory):
    lead_id = await create_lead(session_factory)
    settings = Settings(_env_file=None, web_enabled=True, instagram_provider="replay", web_manager_id=1001)
    app = build_web_app(
        settings,
        WebQueryService(session_factory, hot_threshold=70),
        LeadWorkflowService(session_factory, hot_threshold=70),
        MonitorController(None),  # type: ignore[arg-type]
        crm=CRMService(session_factory),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/leads/{lead_id}")
        agent = await client.post(
            "/api/agent/query",
            json={"query": "Объясни оценку", "lead_id": lead_id},
        )

    assert response.status_code == 200
    assert "lead-agent-panel" in response.text
    assert f'name="lead_id" value="{lead_id}"' in response.text
    assert "data-agent-query" in response.text
    assert agent.status_code == 200
    assert agent.json()["grounded"] is True
    assert agent.json()["tool_calls"][0]["tool_name"] == "lead.explain_score"


async def test_contact_detail_renders_grounded_agent_panel(session_factory):
    lead_id = await create_lead(session_factory)
    settings = Settings(_env_file=None, web_enabled=True, instagram_provider="replay", web_manager_id=1001)
    queries = WebQueryService(session_factory, hot_threshold=70)
    app = build_web_app(
        settings,
        queries,
        LeadWorkflowService(session_factory, hot_threshold=70),
        MonitorController(None),  # type: ignore[arg-type]
        crm=CRMService(session_factory),
    )
    lead_data = await queries.lead_detail(lead_id)
    assert lead_data is not None
    contact_id = lead_data["contact"].id

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/contacts/{contact_id}")
        agent = await client.post(
            "/api/agent/query",
            json={"query": "Объясни оценку", "lead_id": lead_id},
        )

    assert response.status_code == 200
    assert "lead-agent-panel" in response.text
    assert f'value="{lead_id}"' in response.text
    assert "@user-1" in response.text
    assert "contact-agent-result" in response.text
    assert "data-agent-query" in response.text
    assert agent.status_code == 200
    assert agent.json()["grounded"] is True
