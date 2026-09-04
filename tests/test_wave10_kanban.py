from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.db.models import ContactEvent, ContactEventType, Deal, DealStatus, Lead, LeadStatus
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
    """API-эквивалент drop: NEW → TAKEN → CONTACTED; WON/LOST только через сделку."""
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
        blocked_from_contacted = await client.post(
            f"/api/leads/{lead_id}/stage", json={"status": "WON"}
        )
        await client.post(f"/api/leads/{lead_id}/stage", json={"status": "QUALIFIED"})
        await client.post(f"/api/leads/{lead_id}/stage", json={"status": "OFFER_SENT"})
        blocked_won = await client.post(f"/api/leads/{lead_id}/stage", json={"status": "WON"})
        blocked_lost = await client.post(f"/api/leads/{lead_id}/stage", json={"status": "LOST"})
        negotiation = await client.post(
            f"/api/leads/{lead_id}/stage", json={"status": "NEGOTIATION"}
        )
        blocked_won_from_nego = await client.post(
            f"/api/leads/{lead_id}/stage", json={"status": "WON"}
        )
    assert taken.status_code == 200
    assert contacted.status_code == 200
    assert contacted.json()["status"] == "CONTACTED"
    assert blocked_from_contacted.status_code == 409
    assert negotiation.status_code == 200
    assert blocked_won.status_code == 409
    assert blocked_lost.status_code == 409
    assert blocked_won_from_nego.status_code == 409
    assert "сделк" in blocked_won.json()["detail"].lower()


async def test_stage_toward_chains_new_to_offer(session_factory):
    """Операторский drop на «Предложение»: NEW → … → OFFER_SENT одной командой."""
    lead_id = await create_lead(session_factory)
    settings = Settings(
        _env_file=None, web_enabled=True, instagram_provider="replay", web_manager_id=1001
    )
    app = build_web_app(
        settings,
        WebQueryService(session_factory, hot_threshold=70),
        LeadWorkflowService(session_factory, hot_threshold=70),
        MonitorController(None),  # type: ignore[arg-type]
        crm=CRMService(session_factory),
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        jumped = await client.post(
            f"/api/leads/{lead_id}/stage", json={"status": "OFFER_SENT"}
        )
    assert jumped.status_code == 200
    assert jumped.json()["status"] == "OFFER_SENT"


async def test_stage_taken_sets_manager_assigned_and_feedback(session_factory):
    from sqlalchemy import select

    from app.db.models import AIFeedback, ContactEvent, ContactEventType

    lead_id = await create_lead(session_factory)
    crm = CRMService(session_factory)
    lead = await crm.move_lead(lead_id, 1001, LeadStatus.TAKEN)
    assert lead.status == LeadStatus.TAKEN
    assert lead.assigned_manager_telegram_id == 1001

    async with session_factory() as session:
        feedback = await session.scalar(select(AIFeedback).where(AIFeedback.lead_id == lead_id))
        assert feedback is not None
        assert feedback.manager_is_lead is True
        events = list(
            await session.scalars(
                select(ContactEvent)
                .where(ContactEvent.lead_id == lead_id)
                .order_by(ContactEvent.id.desc())
            )
        )
    assert any(event.event_type == ContactEventType.MANAGER_ASSIGNED for event in events)


def test_kanban_drag_drop_js_wired():
    js = Path("app/web/static/app.js").read_text(encoding="utf-8")
    assert "enhanceKanbanDragDrop" in js
    assert "data-kanban-drag-handle" in js
    assert "CLOSED_STAGES" in js
    assert "dropInFlight" in js
    assert "kanbanDropStatus" in js


async def test_leads_board_shows_ai_pending_columns(session_factory):
    lead_id = await create_lead(session_factory)
    async with session_factory() as session:
        lead = await session.get(Lead, lead_id)
        assert lead is not None
        lead.status = LeadStatus.AI_PENDING
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
    assert 'data-operator-board' in html
    assert 'data-kanban-col-key="pending"' in html
    assert 'data-kanban-stages="ANALYZING,AI_PENDING"' in html
    assert f'data-lead-card="{lead_id}"' in html
    assert 'data-lead-stage="AI_PENDING"' in html


async def test_dashboard_revenue_none_shows_em_dash(session_factory):
    """Без полного UZS snapshot выручка на обзоре — «—», не «0»."""
    lead_id = await create_lead(session_factory)
    async with session_factory() as session:
        lead = await session.get(Lead, lead_id)
        assert lead is not None
        lead.status = LeadStatus.WON
        session.add(
            Deal(
                lead_id=lead.id,
                contact_id=lead.contact_id,
                status=DealStatus.WON,
                product_name="Test",
                amount=Decimal("100000"),
                final_amount=Decimal("100000"),
                quantity=1,
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
        response = await client.get("/")
    assert response.status_code == 200
    assert "Продажи" in response.text
    assert ">—</small>" in response.text or ">——<" in response.text or ">—<" in response.text
    assert "0 сум" not in response.text


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
