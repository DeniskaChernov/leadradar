"""HTTP и config checks для deployment readiness (Stage 9)."""

from __future__ import annotations

import asyncio
import threading
import time

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.services import deployment_readiness_service
from app.services.deployment_readiness_service import inspect_offline_readiness
from app.services.lead_workflow_service import LeadWorkflowService
from app.services.monitor_controller import MonitorController
from app.web.app import build_web_app
from app.web.queries import WebQueryService
from tests.test_web_security import FakeMonitor


@pytest.mark.asyncio
async def test_offline_readiness_passes_for_test_database(migrated_database):
    settings = Settings(_env_file=None)
    state = await inspect_offline_readiness(settings)
    assert state.database_healthy is True
    assert state.migration_at_head is True
    assert state.migration_drift_free is True
    assert state.ready is True
    assert state.offline_blocks == ()


@pytest.mark.asyncio
async def test_ready_endpoint_returns_200_when_database_is_healthy(session_factory, migrated_database):
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


@pytest.mark.asyncio
async def test_concurrent_readiness_checks_do_not_overlap_alembic_context(
    migrated_database, monkeypatch,
):
    original_check = deployment_readiness_service.command.check
    entered = threading.Lock()
    calls = 0

    def guarded_check(config):
        nonlocal calls
        if not entered.acquire(blocking=False):
            raise RuntimeError("Alembic's module context is already in use")
        try:
            calls += 1
            time.sleep(0.05)
            return original_check(config)
        finally:
            entered.release()

    monkeypatch.setattr(deployment_readiness_service.command, "check", guarded_check)
    settings = Settings(_env_file=None)
    results = await asyncio.gather(*(inspect_offline_readiness(settings) for _ in range(3)))
    assert calls == 3
    assert all(result.ready and result.offline_blocks == () for result in results)


@pytest.mark.asyncio
async def test_failed_migration_check_is_reported_and_next_check_can_run(
    migrated_database, monkeypatch,
):
    original_check = deployment_readiness_service.command.check
    calls = 0

    def fail_once(config):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("Schema drift detected")
        return original_check(config)

    monkeypatch.setattr(deployment_readiness_service.command, "check", fail_once)
    settings = Settings(_env_file=None)
    failed = await inspect_offline_readiness(settings)
    assert not failed.ready
    assert failed.database_healthy and failed.migration_at_head
    assert "Schema drift detected" in failed.migration_error
    assert failed.offline_blocks
    recovered = await inspect_offline_readiness(settings)
    assert recovered.ready
    assert recovered.offline_blocks == ()
