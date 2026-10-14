import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.db.models import ContactEvent, Lead, LeadStatus
from app.services.qualification_explanation import qualification_explanation
from tests.test_free_pending_review import make_app
from tests.test_lead_workflow import create_lead


@pytest.mark.parametrize("status,assortment,state", [
    (LeadStatus.AI_PENDING, {}, "PENDING"), (LeadStatus.ANALYZING, {}, "PENDING"),
    (LeadStatus.NOT_LEAD, {"status": "EXCLUDED"}, "EXCLUDED"),
    (LeadStatus.NOT_LEAD, {"status": "REVIEW"}, "REJECTED"),
    (LeadStatus.NEW, {"status": "REVIEW"}, "REVIEW"),
    (LeadStatus.NEW, {"status": "MATCH"}, "ASSESSED"),
])
def test_explanation_distinguishes_a_request_from_an_unfinished_or_rejected_signal(status, assortment, state):
    result = qualification_explanation(status, {"assortment": assortment})
    assert result["state"] == state and result["title"] and result["action"]


async def test_explain_returns_grounded_context_and_does_not_write_history(session_factory):
    lead_id = await create_lead(session_factory)
    async with session_factory() as session:
        lead = await session.get(Lead, lead_id)
        lead.status = LeadStatus.NEW
        lead.analysis_details = {"assortment": {"status": "REVIEW", "reason": "Не установлена модель"},
                                 "product_context": {"source": "COMMENT"}}
        await session.commit()
        before = [(e.id, e.payload_json) for e in await session.scalars(select(ContactEvent).order_by(ContactEvent.id))]
    app = await make_app(session_factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        reply = await client.get(f"/api/leads/{lead_id}/explain")
    assert reply.status_code == 200
    detail = reply.json()["qualification"]
    assert detail["state"] == "REVIEW" and "комментария клиента" in detail["product_source"]
    assert detail["assortment_reason"] == "Не установлена модель"
    async with session_factory() as session:
        assert [(e.id, e.payload_json) for e in await session.scalars(select(ContactEvent).order_by(ContactEvent.id))] == before
