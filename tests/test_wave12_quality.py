from pathlib import Path

from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.services.contact_service import ContactService
from app.services.crm_service import CRMService
from app.services.lead_service import LeadService
from app.services.lead_workflow_service import LeadWorkflowService
from app.services.monitor_controller import MonitorController
from app.web.app import build_web_app
from app.web.queries import WebQueryService
from tests.test_contact_service import make_comment, make_post
from tests.test_lead_service import StaticAnalyzer
from tests.test_lead_workflow import create_lead


async def test_competitor_detail_has_commercial_trend_sparkline(session_factory):
    contacts = ContactService(session_factory)
    leads = LeadService(session_factory, StaticAnalyzer(), hot_threshold=70)
    first = await contacts.persist_signal(make_post(), make_comment("trend-first"))
    await leads.process_signal(first)

    queries = WebQueryService(session_factory, hot_threshold=70)
    rows = await queries.competitors()
    competitor = next(item for item in rows if item["competitor"].normalized_handle == "aiko.uz")
    detail = await queries.competitor_intelligence(competitor["competitor"].id)

    assert detail is not None
    assert "commercial_trend" in detail
    assert len(detail["commercial_trend"]) == 8
    assert "rate" in detail["commercial_trend"][0]

    settings = Settings(_env_file=None, web_enabled=True, instagram_provider="replay", web_manager_id=1001)
    app = build_web_app(
        settings,
        queries,
        LeadWorkflowService(session_factory, hot_threshold=70),
        MonitorController(None),  # type: ignore[arg-type]
        crm=CRMService(session_factory),
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/competitors/{competitor['competitor'].id}")

    assert response.status_code == 200
    assert "commercial-trend-sparkline" in response.text


async def test_competitors_page_has_overlap_graph(session_factory):
    contacts = ContactService(session_factory)
    leads = LeadService(session_factory, StaticAnalyzer(), hot_threshold=70)
    first = await contacts.persist_signal(make_post(), make_comment("graph-aiko"))
    other_post = make_post().model_copy(
        update={
            "platform_post_id": "graph-chinar-post",
            "competitor": "chinar.uz",
            "url": "https://www.instagram.com/reel/graph-chinar-post/",
        }
    )
    second = await contacts.persist_signal(other_post, make_comment("graph-chinar"))
    await leads.process_signal(first)
    await leads.process_signal(second)

    settings = Settings(_env_file=None, web_enabled=True, instagram_provider="replay", web_manager_id=1001)
    app = build_web_app(
        settings,
        WebQueryService(session_factory, hot_threshold=70),
        LeadWorkflowService(session_factory, hot_threshold=70),
        MonitorController(None),  # type: ignore[arg-type]
        crm=CRMService(session_factory),
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/competitors")

    assert response.status_code == 200
    html = response.text
    assert "overlap-graph-svg" in html
    assert "overlap-graph-node" in html


async def test_agent_page_resolves_contact_from_lead(session_factory):
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
        response = await client.get(f"/agent?lead_id={lead_id}")

    assert response.status_code == 200
    html = response.text
    assert f'data-lead-id="{lead_id}"' in html
    assert "data-contact-id=" in html
    assert "Ответы можно сохранить в заметку" in html


async def test_contact_detail_page_renders(session_factory):
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
        lead_response = await client.get(f"/leads/{lead_id}")
    assert lead_response.status_code == 200
    contact_href = lead_response.text.split('/contacts/')[1].split('"')[0]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/contacts/{contact_href}")

    assert response.status_code == 200
    assert "data-lucide=" in response.text


def test_contact_detail_template_uses_lucide_empty_icons():
    html = Path(__file__).resolve().parents[1].joinpath("app/web/templates/contact_detail.html").read_text(
        encoding="utf-8"
    )
    assert 'data-lucide="message-circle"' in html
    assert 'data-lucide="handshake"' in html
    assert "💬" not in html


def test_btn_tiny_has_single_canonical_rule():
    css = Path(__file__).resolve().parents[1] / "app/web/static/app.css"
    text = css.read_text(encoding="utf-8")
    assert text.count(".btn.tiny,") == 1
    assert ".btn.tiny { min-height: 32px" not in text
    assert "min-height: 34px" in text
