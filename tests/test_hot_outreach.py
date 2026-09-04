"""HOT outreach: очередь, подготовка текста, «Отправил» → OFFER_SENT."""

from __future__ import annotations

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.config import Settings
from app.db.models import Contact, ContactEvent, ContactEventType, Lead, LeadStatus
from app.services.contact_service import ContactService
from app.services.crm_service import CRMService
from app.services.hot_outreach_service import HotOutreachService, StaticOutreachComposer
from app.services.lead_service import LeadService
from app.services.lead_workflow_service import LeadWorkflowService
from app.services.monitor_controller import MonitorController
from app.services.product_catalog_service import ProductCatalogService
from app.services.usage_service import ExternalUsageService
from app.web.app import build_web_app
from app.web.queries import WebQueryService
from tests.test_contact_service import make_comment, make_post
from tests.test_lead_service import StaticAnalyzer
from tests.test_live_scan_guard import FakeMonitor


async def _make_hot_lead(session_factory) -> int:
    signal = await ContactService(session_factory).persist_signal(
        make_post(),
        make_comment("hot-outreach-1").model_copy(
            update={
                "platform_comment_id": "hot-outreach-1",
                "text": "Сколько стоит комплект? Нужен срочно",
            }
        ),
    )
    result = await LeadService(
        session_factory, StaticAnalyzer(), hot_threshold=70
    ).process_signal(signal)
    assert result is not None
    return result.lead_id


async def test_hot_prepare_and_mark_sent_advances_funnel(session_factory):
    lead_id = await _make_hot_lead(session_factory)
    workflow = LeadWorkflowService(session_factory, hot_threshold=70)
    crm = CRMService(session_factory)
    service = HotOutreachService(
        session_factory,
        hot_threshold=70,
        workflow=workflow,
        crm=crm,
        catalog=ProductCatalogService(session_factory),
        composer=StaticOutreachComposer("Тестовое предложение для Instagram"),
    )

    queue = await service.queue(vertical="FURNITURE")
    assert any(item["lead_id"] == lead_id for item in queue)

    prepared = await service.prepare(lead_id, manager_id=1001)
    assert prepared["status"] == LeadStatus.TAKEN.value
    assert prepared["draft"]["message"] == "Тестовое предложение для Instagram"
    assert prepared["can_mark_sent"] is True
    assert "contact_history" in prepared

    sent = await service.mark_sent(lead_id, manager_id=1001)
    assert sent["status"] == LeadStatus.OFFER_SENT.value
    assert sent["draft"]["sent_at"]
    assert sent["can_mark_sent"] is False
    assert sent["next_lead_id"] is None

    async with session_factory() as session:
        lead = await session.get(Lead, lead_id)
        assert lead is not None
        assert lead.status == LeadStatus.OFFER_SENT
        events = list(
            await session.scalars(
                select(ContactEvent)
                .where(ContactEvent.lead_id == lead_id)
                .order_by(ContactEvent.id)
            )
        )
        kinds = [
            (event.event_type, (event.payload_json or {}).get("kind"))
            for event in events
        ]
        assert (ContactEventType.NOTE_ADDED, "hot_outreach_prepared") in kinds
        assert (ContactEventType.NOTE_ADDED, "hot_outreach_sent") in kinds
        assert ContactEventType.OFFER_SENT in {event.event_type for event in events}


async def test_hot_mark_sent_returns_next_lead(session_factory):
    first_id = await _make_hot_lead(session_factory)
    second = await ContactService(session_factory).persist_signal(
        make_post(),
        make_comment("hot-outreach-2").model_copy(
            update={
                "platform_comment_id": "hot-outreach-2",
                "platform_user_id": "user-hot-2",
                "username": "second_hot_user",
                "profile_url": "https://www.instagram.com/second_hot_user/",
                "text": "Хочу такой же комплект, цена?",
            }
        ),
    )
    second_result = await LeadService(
        session_factory, StaticAnalyzer(), hot_threshold=70
    ).process_signal(second)
    assert second_result is not None
    second_id = second_result.lead_id

    service = HotOutreachService(
        session_factory,
        hot_threshold=70,
        workflow=LeadWorkflowService(session_factory, hot_threshold=70),
        crm=CRMService(session_factory),
        catalog=ProductCatalogService(session_factory),
        composer=StaticOutreachComposer("Текст A"),
    )
    await service.prepare(first_id, 1001)
    sent = await service.mark_sent(first_id, 1001)
    assert sent["next_lead_id"] == second_id


async def test_hot_already_contacted_flag(session_factory):
    first_id = await _make_hot_lead(session_factory)
    service = HotOutreachService(
        session_factory,
        hot_threshold=70,
        workflow=LeadWorkflowService(session_factory, hot_threshold=70),
        crm=CRMService(session_factory),
        catalog=ProductCatalogService(session_factory),
        composer=StaticOutreachComposer("Текст повтор"),
    )
    await service.prepare(first_id, 1001)
    await service.mark_sent(first_id, 1001)

    async with session_factory() as session:
        first = await session.get(Lead, first_id)
        assert first is not None
        contact = await session.get(Contact, first.contact_id)
        assert contact is not None
        username = contact.username
        platform_user_id = contact.platform_user_id

    twin = await ContactService(session_factory).persist_signal(
        make_post(),
        make_comment("hot-outreach-twin").model_copy(
            update={
                "platform_comment_id": "hot-outreach-twin",
                "platform_user_id": platform_user_id,
                "username": username,
                "text": "Ещё раз интересует цена комплекта",
            }
        ),
    )
    twin_result = await LeadService(
        session_factory, StaticAnalyzer(), hot_threshold=70
    ).process_signal(twin)
    assert twin_result is not None
    detail = await service.detail(twin_result.lead_id)
    assert detail is not None
    assert detail["contact_history"]["already_contacted"] is True
    queue = await service.queue(vertical="FURNITURE")
    twin_item = next(item for item in queue if item["lead_id"] == twin_result.lead_id)
    assert twin_item["already_contacted"] is True

async def test_hot_page_and_apis(session_factory):
    lead_id = await _make_hot_lead(session_factory)
    settings = Settings(
        _env_file=None,
        lead_search_enabled=True,
        web_enabled=True,
        instagram_provider="mock",
        web_manager_id=1001,
        openai_api_key="",
        openai_live_enabled=False,
    )
    workflow = LeadWorkflowService(session_factory, hot_threshold=70)
    controller = MonitorController(FakeMonitor())  # type: ignore[arg-type]
    app = build_web_app(
        settings,
        WebQueryService(session_factory, hot_threshold=70),
        workflow,
        controller,
        ExternalUsageService(session_factory),
    )
    service = HotOutreachService(
        session_factory,
        hot_threshold=70,
        workflow=workflow,
        crm=CRMService(session_factory),
        catalog=ProductCatalogService(session_factory),
        composer=StaticOutreachComposer("Готовый текст"),
    )
    await service.prepare(lead_id, 1001)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        page = await client.get(f"/hot?lead_id={lead_id}")
        blocked = await client.post(f"/api/hot/{lead_id}/prepare", json={})
        marked = await client.post(f"/api/hot/{lead_id}/sent", json={})
        leads_rattan = await client.get("/leads?vertical=ARTIFICIAL_RATTAN")

    assert page.status_code == 200
    assert "HOT очередь" in page.text or "Написать сейчас" in page.text or "Кого писать" in page.text
    assert "data-hot-workspace" in page.text
    assert "GPT сегодня" in page.text or "OpenAI выключен" in page.text
    assert blocked.status_code == 409
    assert marked.status_code == 200
    body = marked.json()
    assert body["detail"]["status"] == LeadStatus.OFFER_SENT.value
    assert "next_url" in body
    assert leads_rattan.status_code == 200
    assert "Лиды ротанга" in leads_rattan.text or "Клиенты · ротанг" in leads_rattan.text
    assert 'href="/leads?vertical=ARTIFICIAL_RATTAN"' in leads_rattan.text or "vertical=ARTIFICIAL_RATTAN" in leads_rattan.text
