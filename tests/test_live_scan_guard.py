from __future__ import annotations

from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.db.models import ProviderBudgetPolicy
from app.services.instagram_monitor import CycleStats
from app.services.lead_workflow_service import LeadWorkflowService
from app.services.monitor_controller import MonitorController
from app.services.operational_control_service import OperationalControlService
from app.services.usage_service import ExternalUsageService
from app.web.app import build_web_app
from app.web.queries import WebQueryService


class FakeMonitor:
    provider = None

    async def run_cycle(self, *, force: bool = True) -> CycleStats:
        return CycleStats(competitors_checked=1)


async def test_live_scan_requires_server_side_confirmation(session_factory):
    async with session_factory() as session:
        session.add(
            ProviderBudgetPolicy(
                provider="scrapecreators",
                service="instagram",
                monthly_target_units=3000,
                monthly_soft_limit_units=3500,
                monthly_hard_limit_units=3800,
                default_scan_budget_units=10,
                maximum_manual_scan_budget_units=50,
                target_minimum_months=6,
                comments_target_units=2400,
                discovery_target_units=600,
                enrichment_target_units=200,
                reserve_target_units=600,
                active=True,
            )
        )
        await session.commit()
    settings = Settings(
        _env_file=None,
        lead_search_enabled=True,
        web_enabled=True,
        instagram_provider="scrapecreators",
        instagram_live_calls_enabled=True,
        external_live_unlock="ALLOW_EXTERNAL_CALLS",
        external_kill_switch=False,
        instagram_max_units_per_scan=2,
        instagram_daily_request_limit=10,
        web_manager_id=1001,
    )
    ops = OperationalControlService(session_factory)
    await ops.load()
    await ops.set_radar_live(True, manager_id=1001)
    controller = MonitorController(FakeMonitor())  # type: ignore[arg-type]
    workflow = LeadWorkflowService(session_factory, hot_threshold=70)
    app = build_web_app(
        settings,
        WebQueryService(session_factory, hot_threshold=70),
        workflow,
        controller,
        ExternalUsageService(session_factory),
        ops_control=ops,
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        radar = await client.get("/radar")
        preview = await client.get("/api/scan/preview?max_credits=10")
        blocked = await client.post("/api/scan", json={"max_credits": 5})
        confirmed = await client.post(
            "/api/scan",
            json={"confirm_live": True, "max_credits": 5},
        )

    assert radar.status_code == 200
    assert "Сколько разрешить на эту проверку?" in radar.text
    assert preview.status_code == 200
    preview_data = preview.json()
    assert preview_data["is_live"] is True
    assert preview_data["requires_confirmation"] is True
    assert preview_data["radar_live_armed"] is True
    assert preview_data["effective_max_credits"] == 10
    assert preview_data["monthly_hard_limit"] == 3800
    assert blocked.status_code == 428
    assert "подтверждения" in blocked.json()["detail"]
    assert confirmed.status_code == 200
    assert confirmed.json()["ok"] is True
    assert confirmed.json()["effective_max_credits"] == 5
    await controller.wait_current()


async def test_safe_replay_scan_does_not_require_confirmation(session_factory):
    settings = Settings(
        _env_file=None,
        lead_search_enabled=True,
        web_enabled=True,
        instagram_provider="replay",
        web_manager_id=1001,
    )
    controller = MonitorController(FakeMonitor())  # type: ignore[arg-type]
    workflow = LeadWorkflowService(session_factory, hot_threshold=70)
    app = build_web_app(
        settings,
        WebQueryService(session_factory, hot_threshold=70),
        workflow,
        controller,
        ExternalUsageService(session_factory),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        radar = await client.get("/radar")
        response = await client.post("/api/scan", json={})

    assert radar.status_code == 200
    assert "Offline-режим" in radar.text
    assert response.status_code == 200
    assert response.json()["ok"] is True
    await controller.wait_current()
