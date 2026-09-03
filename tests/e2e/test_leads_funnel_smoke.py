"""E2E smoke: /leads funnel (HTTP-level, без браузера)."""

from httpx import ASGITransport, AsyncClient

from app.db.models import LeadStatus
from tests.e2e.helpers import build_e2e_app
from tests.test_lead_workflow import create_lead


async def test_leads_page_renders_kanban_funnel(session_factory):
    lead_id = await create_lead(session_factory)
    app = build_e2e_app(session_factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        board = await client.get("/leads")
        detail = await client.get(f"/leads/{lead_id}")
    assert board.status_code == 200
    assert "data-kanban-board" in board.text
    assert "funnel-track" in detail.text
    assert "stage-actions" in detail.text


async def test_leads_funnel_full_api_chain(session_factory):
    lead_id = await create_lead(session_factory)
    app = build_e2e_app(session_factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        taken = await client.post(f"/api/leads/{lead_id}/take", json={})
        contacted = await client.post(
            f"/api/leads/{lead_id}/stage",
            json={"status": LeadStatus.CONTACTED.value},
        )
        not_lead = await client.post(f"/api/leads/{lead_id}/not-lead", json={})
        reopened = await client.post(f"/api/leads/{lead_id}/reopen", json={})
    assert taken.status_code == 200
    assert contacted.status_code == 200
    assert not_lead.status_code == 200
    assert reopened.status_code == 200
    assert taken.json().get("ok") is True
    assert reopened.json().get("ok") is True
    assert reopened.json().get("status") in {
        LeadStatus.NEW.value,
        LeadStatus.TAKEN.value,
        "NEW",
        "TAKEN",
    }
