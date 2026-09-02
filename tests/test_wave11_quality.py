import asyncio

from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.services.crm_service import CRMService
from app.services.lead_workflow_service import LeadWorkflowService
from app.services.monitor_controller import MonitorController
from app.web.app import build_web_app
from app.web.queries import WebQueryService
from scripts.check_data_integrity import inspect_integrity
from tests.test_lead_workflow import create_lead


async def test_economics_page_has_budget_simulation_slider(session_factory):
    settings = Settings(_env_file=None, web_enabled=True, instagram_provider="replay", web_manager_id=1001)
    app = build_web_app(
        settings,
        WebQueryService(session_factory, hot_threshold=70),
        LeadWorkflowService(session_factory, hot_threshold=70),
        MonitorController(None),  # type: ignore[arg-type]
        crm=CRMService(session_factory),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/economics?days=30")

    assert response.status_code == 200
    html = response.text
    assert "data-economics-budget-sim" in html
    assert "data-budget-sim-slider" in html


async def test_system_page_shows_ai_version_info(session_factory):
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

    assert response.status_code == 200
    html = response.text
    assert "ai-version-info" in html
    assert "lead-v3.1-validated-history" in html


async def test_lead_detail_shows_prompt_version(session_factory):
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

    assert response.status_code == 200
    assert "lead-v3.1-validated-history" in response.text
    assert "lead-analysis-v3.2" in response.text


async def test_radar_baseline_archive_filter(session_factory):
    settings = Settings(_env_file=None, web_enabled=True, instagram_provider="replay", web_manager_id=1001)
    app = build_web_app(
        settings,
        WebQueryService(session_factory, hot_threshold=70),
        LeadWorkflowService(session_factory, hot_threshold=70),
        MonitorController(None),  # type: ignore[arg-type]
        crm=CRMService(session_factory),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/radar?kind=baseline")

    assert response.status_code == 200
    assert "Baseline архив" in response.text


def test_integrity_reports_orphan_leads_check():
    result = asyncio.run(inspect_integrity())
    assert "leads without comments" in result.duplicates
