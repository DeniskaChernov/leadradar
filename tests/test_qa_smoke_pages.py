"""Smoke tests: основные страницы и API отдают 200 без 500."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.services.crm_service import CRMService
from app.services.lead_workflow_service import LeadWorkflowService
from app.services.monitor_controller import MonitorController
from app.web.app import build_web_app
from app.web.queries import WebQueryService
from tests.test_lead_workflow import create_lead


def _app(session_factory):
    return build_web_app(
        Settings(
            _env_file=None,
            web_enabled=True,
            instagram_provider="replay",
            web_manager_id=1001,
        ),
        WebQueryService(session_factory, hot_threshold=70),
        LeadWorkflowService(session_factory, hot_threshold=70),
        MonitorController(None),  # type: ignore[arg-type]
        crm=CRMService(session_factory),
    )


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/radar",
        "/leads",
        "/contacts",
        "/tasks",
        "/deals",
        "/economics",
        "/economics?days=7",
        "/economics?days=1",
        "/analytics",
        "/competitors",
        "/catalog",
        "/system",
        "/agent",
        "/discovery",
        "/openings",
        "/audiences",
        "/roadmap",
    ],
)
async def test_public_pages_render_200(session_factory, path: str):
    app = _app(session_factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(path)
    assert response.status_code == 200, f"{path} returned {response.status_code}"


async def test_lead_detail_and_contact_detail_render(session_factory):
    lead_id = await create_lead(session_factory)
    app = _app(session_factory)
    queries = WebQueryService(session_factory, hot_threshold=70)
    detail = await queries.lead_detail(lead_id)
    assert detail is not None
    contact_id = detail["contact"].id
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        lead = await client.get(f"/leads/{lead_id}")
        contact = await client.get(f"/contacts/{contact_id}")
    assert lead.status_code == 200
    assert contact.status_code == 200
    assert "funnel-track" in lead.text
    assert "stage-actions" in lead.text


async def test_economics_page_shows_confirmed_and_estimated_credits(session_factory):
    app = _app(session_factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/economics?days=30")
    assert response.status_code == 200
    text = response.text
    assert "Confirmed credits" in text or "Подтверждённые credits" in text
    assert "Estimated credits" in text or "Оценочные credits" in text
    assert "economics-table-wrap" in text
    assert "Выручка и маржа" in text


async def test_lead_funnel_api_chain(session_factory):
    lead_id = await create_lead(session_factory)
    app = _app(session_factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        taken = await client.post(f"/api/leads/{lead_id}/take", json={})
        contacted = await client.post(
            f"/api/leads/{lead_id}/stage",
            json={"status": "CONTACTED"},
        )
        bad = await client.post("/api/agent/approve", json={"message_id": "x"})
    assert taken.status_code == 200
    assert contacted.status_code == 200
    assert bad.status_code == 400
