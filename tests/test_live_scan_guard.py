from __future__ import annotations

from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.services.instagram_monitor import CycleStats
from app.services.lead_workflow_service import LeadWorkflowService
from app.services.monitor_controller import MonitorController
from app.services.usage_service import ExternalUsageService
from app.web.app import build_web_app
from app.web.queries import WebQueryService


class FakeMonitor:
    provider = None

    async def run_cycle(self, *, force: bool = True) -> CycleStats:
        return CycleStats(competitors_checked=1)


async def test_live_scan_requires_server_side_confirmation(session_factory):
    settings = Settings(
        _env_file=None,
        lead_search_enabled=True,
        web_enabled=True,
        instagram_provider="scrapecreators",
        instagram_live_calls_enabled=True,
        external_live_unlock="ALLOW_EXTERNAL_CALLS",
        instagram_max_units_per_scan=2,
        instagram_daily_request_limit=10,
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
        preview = await client.get("/api/scan/preview")
        blocked = await client.post("/api/scan", json={})
        confirmed = await client.post("/api/scan", json={"confirm_live": True})

    assert preview.status_code == 200
    preview_data = preview.json()
    assert preview_data["is_live"] is True
    assert preview_data["requires_confirmation"] is True
    assert preview_data["plan"]["hard_cap_units"] == 2
    assert blocked.status_code == 428
    assert "подтверждения" in blocked.json()["detail"]
    assert confirmed.status_code == 200
    assert confirmed.json()["ok"] is True
    await controller.wait_current()


async def test_safe_replay_scan_does_not_require_confirmation(session_factory):
    settings = Settings(
        _env_file=None,
        lead_search_enabled=True,
        web_enabled=True,
        instagram_provider="replay",
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
        response = await client.post("/api/scan", json={})

    assert response.status_code == 200
    assert response.json()["ok"] is True
    await controller.wait_current()
