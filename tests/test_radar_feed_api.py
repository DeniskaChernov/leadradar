"""API /api/radar/feed — регрессия intent как plain string и поля pipeline."""

from __future__ import annotations

from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.db.models import LeadStatus
from app.services.contact_service import ContactService
from app.services.instagram_monitor import CycleStats
from app.services.lead_analysis_pipeline import LeadAnalysisPipeline
from app.services.lead_service import LeadService
from app.services.lead_workflow_service import LeadWorkflowService
from app.services.monitor_controller import MonitorController
from app.services.operational_control_service import OperationalControlService
from app.services.usage_service import ExternalUsageService
from app.web.app import build_web_app
from app.web.queries import WebQueryService
from tests.test_contact_service import make_comment, make_post
from tests.test_lead_service import StaticAnalyzer


class FakeMonitor:
    provider = None

    async def run_cycle(self, *, force: bool = True) -> CycleStats:
        return CycleStats()


async def _hot_lead_app(session_factory, *, with_pipeline: bool = True):
    signal = await ContactService(session_factory).persist_signal(make_post(), make_comment())
    service = LeadService(session_factory, StaticAnalyzer(), hot_threshold=70)
    result = await service.process_signal(signal)
    assert result is not None
    async with session_factory() as session:
        from sqlalchemy import select

        from app.db.models import Lead

        lead = await session.scalar(select(Lead).where(Lead.id == result.lead_id))
        assert lead is not None
        lead.status = LeadStatus.NEW
        lead.lead_score = 91
        lead.intent = "PRICE"
        await session.commit()

    settings = Settings(_env_file=None, web_enabled=True, web_manager_id=1001)
    ops = OperationalControlService(session_factory)
    await ops.load()
    workflow = LeadWorkflowService(session_factory, hot_threshold=70)
    pipeline = None
    if with_pipeline:
        pipeline = LeadAnalysisPipeline(service, object(), sync_mode=True)  # type: ignore[arg-type]
    return build_web_app(
        settings,
        WebQueryService(session_factory, hot_threshold=70),
        workflow,
        MonitorController(FakeMonitor()),  # type: ignore[arg-type]
        ExternalUsageService(session_factory),
        ops_control=ops,
        analysis_pipeline=pipeline,
    )


async def test_radar_feed_hot_lead_intent_is_plain_string(session_factory):
    app = await _hot_lead_app(session_factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/radar/feed?limit=5")

    assert response.status_code == 200
    payload = response.json()
    assert payload["hot_leads"]
    assert payload["hot_leads"][0]["intent"] == "PRICE"
    assert isinstance(payload["hot_leads"][0]["intent"], str)
    assert "overview" in payload
    assert "changes" in payload


async def test_radar_feed_exposes_pipeline_counters(session_factory):
    app = await _hot_lead_app(session_factory, with_pipeline=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/radar/feed")

    assert response.status_code == 200
    payload = response.json()
    assert payload["analysis_queue"] == 0
    assert payload["analysis_in_flight"] == 0
    assert payload["cycle_running"] is False
    assert payload["ai_analysis_max_concurrency"] >= 1
    assert "scan_progress" in payload
    assert payload["scan_progress"]["phase"] == "idle"


async def test_scan_progress_api_returns_idle_snapshot(session_factory):
    app = await _hot_lead_app(session_factory, with_pipeline=False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/scan/progress")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["cycle_running"] is False
    assert payload["progress"]["phase"] == "idle"
    assert payload["progress"]["percent"] == 0
    assert "last_stats" in payload
    assert payload["last_stats"] is None
