"""HTTP и config checks для deployment readiness (Stage 9)."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.services.deployment_readiness_service import inspect_offline_readiness
from app.services.lead_workflow_service import LeadWorkflowService
from app.services.monitor_controller import MonitorController
from app.web.app import build_web_app
from app.web.queries import WebQueryService
from tests.test_web_security import FakeMonitor


@pytest.mark.asyncio
async def test_offline_readiness_passes_for_test_database(session_factory):
    settings = Settings(_env_file=None)
    state = await inspect_offline_readiness(settings)
    assert state.database_healthy is True
    assert state.migration_at_head is True
    assert state.migration_drift_free is True
    assert state.ready is True
    assert state.offline_blocks == ()


@pytest.mark.asyncio
async def test_ready_endpoint_returns_200_when_database_is_healthy(session_factory):
    settings = Settings(_env_file=None, web_enabled=True, instagram_provider="replay")
    workflow = LeadWorkflowService(session_factory, hot_threshold=70)
    app = build_web_app(
        settings,
        WebQueryService(session_factory, hot_threshold=70),
        workflow,
        MonitorController(FakeMonitor()),  # type: ignore[arg-type]
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/ready")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["database_healthy"] is True
    assert payload["migration_at_head"] is True
    assert payload["migration_drift_free"] is True
    assert payload["blocks"] == []


def test_platform_port_env_overrides_web_port(monkeypatch):
    monkeypatch.setenv("PORT", "9876")
    settings = Settings(_env_file=None)
    assert settings.web_port == 9876
