from __future__ import annotations

from httpx import ASGITransport, AsyncClient

from app.config import Settings
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


async def test_ops_radar_toggle_persists_and_gates_scan(session_factory):
    settings = Settings(
        _env_file=None,
        lead_search_enabled=True,
        web_enabled=True,
        instagram_provider="scrapecreators",
        instagram_live_calls_enabled=True,
        external_live_unlock="ALLOW_EXTERNAL_CALLS",
        external_kill_switch=False,
        instagram_daily_request_limit=20,
        instagram_max_units_per_scan=10,
        web_manager_id=1001,
    )
    ops = OperationalControlService(session_factory)
    await ops.load()
    assert ops.radar_live_armed() is False
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
        blocked = await client.post(
            "/api/scan",
            json={"confirm_live": True, "max_credits": 5},
        )
        armed = await client.post("/api/ops/radar-live", json={"armed": True, "default_scan_credits": 5})
        preview = await client.get("/api/scan/preview?max_credits=5")

    assert blocked.status_code == 409
    assert armed.status_code == 200
    assert armed.json()["radar_live_armed"] is True
    assert ops.radar_live_armed() is True
    assert preview.json()["radar_live_armed"] is True
    assert preview.json()["live_enabled"] is True
