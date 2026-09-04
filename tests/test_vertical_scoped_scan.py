"""Мебель и ротанг — отдельные портфели скана/радара."""

from __future__ import annotations

from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.db.models import Competitor, Vertical
from app.services.adaptive_monitoring_service import AdaptiveMonitoringService
from app.services.instagram_monitor import CycleStats
from app.services.lead_workflow_service import LeadWorkflowService
from app.services.monitor_controller import MonitorController
from app.services.operational_control_service import OperationalControlService
from app.services.usage_service import ExternalUsageService
from app.web.app import build_web_app
from app.web.queries import WebQueryService


class CapturingMonitor:
    """Фиксирует vertical, переданный в run_cycle."""

    provider = None
    last_vertical: str | None = None

    async def run_cycle(
        self, *, force: bool = True, vertical: str | None = None
    ) -> CycleStats:
        self.last_vertical = vertical
        return CycleStats(competitors_checked=1)


async def _seed_two_verticals(session_factory) -> None:
    async with session_factory() as session:
        session.add_all(
            [
                Competitor(
                    handle="aiko.uz",
                    normalized_handle="aiko.uz",
                    vertical=Vertical.FURNITURE,
                    active=True,
                    tier="A",
                ),
                Competitor(
                    handle="botanist_kg",
                    normalized_handle="botanist_kg",
                    vertical=Vertical.ARTIFICIAL_RATTAN,
                    active=True,
                    tier="A",
                ),
                Competitor(
                    handle="paused_rattan",
                    normalized_handle="paused_rattan",
                    vertical=Vertical.ARTIFICIAL_RATTAN,
                    active=False,
                    tier="B",
                ),
            ]
        )
        await session.commit()


async def test_ranked_due_competitors_respects_vertical(session_factory):
    await _seed_two_verticals(session_factory)
    service = AdaptiveMonitoringService(session_factory, hot_threshold=70)

    furniture, _ = await service.ranked_due_competitors([], force=True, vertical="FURNITURE")
    rattan, _ = await service.ranked_due_competitors(
        [], force=True, vertical="ARTIFICIAL_RATTAN"
    )
    all_due, _ = await service.ranked_due_competitors([], force=True)

    assert [c.handle for c in furniture] == ["aiko.uz"]
    assert [c.handle for c in rattan] == ["botanist_kg"]
    assert {c.handle for c in all_due} == {"aiko.uz", "botanist_kg"}


async def test_scan_plan_counts_only_selected_vertical(session_factory):
    await _seed_two_verticals(session_factory)
    queries = WebQueryService(session_factory, hot_threshold=70)

    furniture = await queries.scan_plan(
        max_units_per_scan=100,
        daily_remaining=100,
        live_enabled=True,
        vertical="FURNITURE",
    )
    rattan = await queries.scan_plan(
        max_units_per_scan=100,
        daily_remaining=100,
        live_enabled=True,
        vertical="ARTIFICIAL_RATTAN",
    )

    assert furniture["active_competitors"] == 1
    assert rattan["active_competitors"] == 1
    assert furniture["vertical"] == "FURNITURE"
    assert rattan["vertical"] == "ARTIFICIAL_RATTAN"


async def test_scan_preview_and_start_are_vertical_scoped(session_factory):
    await _seed_two_verticals(session_factory)
    settings = Settings(
        _env_file=None,
        lead_search_enabled=True,
        web_enabled=True,
        instagram_provider="mock",
        instagram_live_calls_enabled=False,
        external_kill_switch=True,
        web_manager_id=1001,
    )
    monitor = CapturingMonitor()
    controller = MonitorController(monitor)  # type: ignore[arg-type]
    ops = OperationalControlService(session_factory)
    await ops.load()
    app = build_web_app(
        settings,
        WebQueryService(session_factory, hot_threshold=70),
        LeadWorkflowService(session_factory, hot_threshold=70),
        controller,
        ExternalUsageService(session_factory),
        ops_control=ops,
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        furniture = await client.get("/api/scan/preview?vertical=FURNITURE")
        rattan = await client.get("/api/scan/preview?vertical=ARTIFICIAL_RATTAN")
        radar_page = await client.get("/radar?vertical=ARTIFICIAL_RATTAN")
        started = await client.post(
            "/api/scan",
            json={"max_credits": 5, "vertical": "ARTIFICIAL_RATTAN"},
        )

    assert furniture.status_code == 200
    assert rattan.status_code == 200
    assert furniture.json()["active_competitors"] == 1
    assert rattan.json()["active_competitors"] == 1
    assert furniture.json()["vertical"] == "FURNITURE"
    assert rattan.json()["vertical"] == "ARTIFICIAL_RATTAN"
    assert radar_page.status_code == 200
    assert "Найти лидов · Ротанг" in radar_page.text or "Найти лидов" in radar_page.text
    assert 'data-scan-vertical="ARTIFICIAL_RATTAN"' in radar_page.text
    assert "data-find-leads" in radar_page.text or "Искусственный ротанг" in radar_page.text
    assert started.status_code == 200
    assert started.json()["ok"] is True
    assert started.json()["vertical"] == "ARTIFICIAL_RATTAN"
    await controller.wait_current()
    assert monitor.last_vertical == "ARTIFICIAL_RATTAN"
