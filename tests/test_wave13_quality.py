from pathlib import Path

from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.db.models import ContactEventType
from app.services.agent_rate_limit_service import AgentRateLimitService
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


def test_agent_rate_limiter_blocks_after_threshold():
    limiter = AgentRateLimitService(max_requests=3, window_seconds=60)
    for _ in range(3):
        result = limiter.check(42)
        assert result.allowed
    blocked = limiter.check(42)
    assert not blocked.allowed
    assert blocked.retry_after_seconds >= 1


def test_compact_contact_events_groups_same_day_noise():
    class StubEvent:
        def __init__(self, event_type, day: str):
            self.event_type = event_type
            self.created_at = __import__("datetime").datetime.fromisoformat(f"{day}T12:00:00+00:00")

    events = [
        StubEvent(ContactEventType.LEAD_SCORE_CHANGED, "2026-09-01"),
        StubEvent(ContactEventType.LEAD_SCORE_CHANGED, "2026-09-01"),
        StubEvent(ContactEventType.NOTE_ADDED, "2026-09-01"),
    ]
    groups = WebQueryService.compact_contact_events(events)  # type: ignore[arg-type]
    assert len(groups) == 2
    assert groups[0]["count"] == 2
    assert groups[1]["count"] == 1


async def test_lead_detail_has_breadcrumbs(session_factory):
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
    html = response.text
    assert 'class="breadcrumbs"' in html
    assert 'aria-label="Навигация по разделам"' in html
    assert 'href="/leads"' in html


async def test_agent_rate_limit_returns_429(session_factory):
    settings = Settings(_env_file=None, web_enabled=True, instagram_provider="replay", web_manager_id=1001)
    app = build_web_app(
        settings,
        WebQueryService(session_factory, hot_threshold=70),
        LeadWorkflowService(session_factory, hot_threshold=70),
        MonitorController(None),  # type: ignore[arg-type]
        crm=CRMService(session_factory),
    )
    import app.web.app as web_app_module
    from app.services.agent_rate_limit_service import AgentRateLimitService

    original = web_app_module.agent_rate_limiter
    web_app_module.agent_rate_limiter = AgentRateLimitService(max_requests=1, window_seconds=60)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            first = await client.post("/api/agent/query", json={"query": "ping one"})
            second = await client.post("/api/agent/query", json={"query": "ping two"})
        assert first.status_code == 200
        assert second.status_code == 429
        assert "Подождите" in second.text
        assert second.headers.get("Retry-After")
    finally:
        web_app_module.agent_rate_limiter = original


async def test_radar_table_uses_responsive_table(session_factory):
    settings = Settings(_env_file=None, web_enabled=True, instagram_provider="replay", web_manager_id=1001)
    app = build_web_app(
        settings,
        WebQueryService(session_factory, hot_threshold=70),
        LeadWorkflowService(session_factory, hot_threshold=70),
        MonitorController(None),  # type: ignore[arg-type]
        crm=CRMService(session_factory),
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/radar")

    assert response.status_code == 200
    assert 'class="responsive-table radar-table"' in response.text


async def test_contact_detail_exposes_event_groups(session_factory):
    contacts = ContactService(session_factory)
    leads = LeadService(session_factory, StaticAnalyzer(), hot_threshold=70)
    signal = await contacts.persist_signal(make_post(), make_comment("group-test"))
    await leads.process_signal(signal)

    queries = WebQueryService(session_factory, hot_threshold=70)
    detail = await queries.contact_detail(signal.contact_id)
    assert detail is not None
    assert "event_groups" in detail
    assert len(detail["event_groups"]) >= 1


def test_templates_include_search_shortcut_targets():
    js = Path(__file__).resolve().parents[1].joinpath("app/web/static/app.js").read_text(encoding="utf-8")
    assert "enhanceGlobalSearchShortcut" in js
    assert ".radar-filters input[name=\"q\"]" in js
