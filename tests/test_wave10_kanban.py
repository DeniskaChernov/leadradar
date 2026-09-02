from datetime import UTC, datetime
from pathlib import Path

from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.db.models import ContactEvent, ContactEventType, Lead
from app.services.crm_service import CRMService
from app.services.lead_workflow_service import LeadWorkflowService
from app.services.monitor_controller import MonitorController
from app.web.app import build_web_app
from app.web.queries import WebQueryService
from tests.test_lead_workflow import create_lead


async def test_lead_recent_events_batch(session_factory):
    lead_id = await create_lead(session_factory)
    async with session_factory() as session:
        lead = await session.get(Lead, lead_id)
        assert lead is not None
        session.add(
            ContactEvent(
                contact_id=lead.contact_id,
                lead_id=lead_id,
                event_type=ContactEventType.NOTE_ADDED,
                payload_json={"text": "Позвонить завтра"},
            )
        )
        await session.commit()

    queries = WebQueryService(session_factory, hot_threshold=70)
    events = await queries.lead_recent_events([lead_id], limit_per_lead=5)
    assert lead_id in events
    assert len(events[lead_id]) >= 1
    assert any(
        event.event_type == ContactEventType.NOTE_ADDED for event in events[lead_id]
    )


async def test_leads_board_includes_event_tip_partial(session_factory):
    lead_id = await create_lead(session_factory)
    async with session_factory() as session:
        lead = await session.get(Lead, lead_id)
        assert lead is not None
        session.add(
            ContactEvent(
                contact_id=lead.contact_id,
                lead_id=lead_id,
                event_type=ContactEventType.NOTE_ADDED,
                payload_json={"text": "Тест tooltip"},
                created_at=datetime.now(UTC),
            )
        )
        await session.commit()

    settings = Settings(_env_file=None, web_enabled=True, instagram_provider="replay", web_manager_id=1001)
    app = build_web_app(
        settings,
        WebQueryService(session_factory, hot_threshold=70),
        LeadWorkflowService(session_factory, hot_threshold=70),
        MonitorController(None),  # type: ignore[arg-type]
        crm=CRMService(session_factory),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/leads")

    assert response.status_code == 200
    html = response.text
    assert "kanban-event-tip-trigger" in html
    assert "kanban-mobile-nav" in html
    assert "data-kanban-board" in html
    assert "kanban-drag-handle" in html
    assert "data-kanban-stage" in html
    assert "data-kanban-drop" in html
    assert "Тест tooltip" in html or "Последние действия" in html


async def test_kanban_drag_drop_stage_api(session_factory):
    """API-эквивалент drop: NEW → TAKEN → CONTACTED."""
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
        taken = await client.post(f"/api/leads/{lead_id}/stage", json={"status": "TAKEN"})
        contacted = await client.post(f"/api/leads/{lead_id}/stage", json={"status": "CONTACTED"})
        blocked = await client.post(f"/api/leads/{lead_id}/stage", json={"status": "WON"})
    assert taken.status_code == 200
    assert contacted.status_code == 200
    assert contacted.json()["status"] == "CONTACTED"
    assert blocked.status_code == 409


def test_kanban_drag_drop_js_wired():
    js = Path("app/web/static/app.js").read_text(encoding="utf-8")
    assert "enhanceKanbanDragDrop" in js
    assert "data-kanban-drag-handle" in js


async def test_reopen_api_after_not_lead(session_factory):
    lead_id = await create_lead(session_factory)
    workflow = LeadWorkflowService(session_factory, hot_threshold=70)
    await workflow.mark_not_lead(lead_id, 1001)

    settings = Settings(_env_file=None, web_enabled=True, instagram_provider="replay", web_manager_id=1001)
    app = build_web_app(
        settings,
        WebQueryService(session_factory, hot_threshold=70),
        workflow,
        MonitorController(None),  # type: ignore[arg-type]
        crm=CRMService(session_factory),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(f"/api/leads/{lead_id}/reopen", json={})

    assert response.status_code == 200
    assert response.json()["ok"] is True
