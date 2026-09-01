"""Smoke tests: основные страницы и API отдают 200 без 500."""

from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.db.models import Competitor, CostEvent
from app.services.audience_service import SEGMENTS, AudienceEngine
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
        "/rattan",
        "/audiences/quality",
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


@pytest.mark.parametrize(
    "path,marker",
    [
        ("/discovery", "ЦЕНТР РАЗВЕДКИ"),
        ("/analytics?days=7", "РЫНОЧНАЯ АНАЛИТИКА"),
        ("/catalog", "ИСТОЧНИК ИСТИНЫ"),
        ("/audiences", "ИНТЕЛЛЕКТ АУДИТОРИЙ"),
        ("/openings", "B2B ОТКРЫТИЯ"),
        ("/agent", "ОБОСНОВАННО"),
    ],
)
async def test_admin_pages_show_russian_eyebrows(session_factory, path: str, marker: str):
    app = _app(session_factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(path)
    assert response.status_code == 200
    assert marker in response.text


@pytest.mark.parametrize(
    "path",
    [
        "/discovery",
        "/analytics?days=7",
        "/catalog",
        "/audiences",
        "/openings",
        "/roadmap",
        "/rattan",
    ],
)
async def test_secondary_pages_have_motion_root(session_factory, path: str):
    app = _app(session_factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(path)
    assert response.status_code == 200
    assert "data-motion-root" in response.text


async def _seed_mixed_credit_events(session_factory) -> None:
    async with session_factory() as session:
        session.add_all(
            [
                CostEvent(
                    idempotency_key="qa:confirmed-credits",
                    service="instagram",
                    provider="scrapecreators",
                    operation="get_comment_batch",
                    units=30,
                    cost_usd=Decimal("0.375000"),
                    unit_source="PROVIDER_CONFIRMED",
                ),
                CostEvent(
                    idempotency_key="qa:estimated-credits",
                    service="instagram",
                    provider="scrapecreators",
                    operation="get_reels",
                    units=10,
                    cost_usd=Decimal("0.100000"),
                    unit_source="ESTIMATED",
                ),
            ]
        )
        await session.commit()


async def test_economics_page_shows_confirmed_estimated_split(session_factory):
    await _seed_mixed_credit_events(session_factory)
    from app.services.economics_page_service import EconomicsPageService

    snapshot = await EconomicsPageService(session_factory, hot_threshold=70).snapshot(30)
    assert snapshot.credits.confirmed_credits == 30
    assert snapshot.credits.estimated_credits == 10
    assert snapshot.credits.confirmed_coverage_percent == Decimal("75.00")

    app = _app(session_factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/economics?days=30")
    assert response.status_code == 200
    text = response.text
    assert "Подтверждённые credits" in text
    assert "Оценочные credits" in text
    assert "75.00%" in text or "75%" in text
    assert "доля подтверждённых" in text


async def _create_competitor(session_factory) -> int:
    async with session_factory() as session:
        competitor = Competitor(
            handle="qa-competitor",
            normalized_handle="qa-competitor",
            display_name="QA Competitor",
            website_url="https://instagram.com/qa-competitor",
        )
        session.add(competitor)
        await session.commit()
        await session.refresh(competitor)
        return competitor.id


async def test_competitor_detail_renders_with_real_id(session_factory):
    competitor_id = await _create_competitor(session_factory)
    app = _app(session_factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/competitors/{competitor_id}")
    assert response.status_code == 200
    assert "РАЗВЕДКА КОНКУРЕНТА" in response.text
    assert "data-motion-root" in response.text
    assert "qa-competitor" in response.text


async def test_audience_detail_renders_with_real_slug(session_factory):
    await AudienceEngine(session_factory, hot_threshold=70).sync_segments()
    slug = SEGMENTS[0].slug
    app = _app(session_factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/audiences/{slug}")
    assert response.status_code == 200
    assert "ИНТЕЛЛЕКТ АУДИТОРИЙ" in response.text
    assert "data-motion-root" in response.text


async def test_audience_quality_page_russian_table_labels(session_factory):
    await AudienceEngine(session_factory, hot_threshold=70).sync_segments()
    app = _app(session_factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/audiences/quality?vertical=FURNITURE")
    assert response.status_code == 200
    text = response.text
    assert "Здоровье, пересечения" in text
    assert 'data-label="Статус"' in text
    assert 'data-label="Увер."' in text
    assert "здоровых" in text


async def test_competitor_detail_404_for_missing_id(session_factory):
    app = _app(session_factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/competitors/999999")
    assert response.status_code == 404
