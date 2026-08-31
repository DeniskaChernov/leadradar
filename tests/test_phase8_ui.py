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


async def test_system_page_renders_agent_and_export_workspaces(session_factory):
    await AudienceEngine(session_factory, hot_threshold=70).sync_segments()
    settings = Settings(_env_file=None, web_enabled=True, instagram_provider="replay")
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
