from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.services.competitor_import_service import CompetitorImportService
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


async def test_competitor_import_creates_paused_competitors(session_factory):
    service = CompetitorImportService(session_factory)
    payload = b"company,instagram,tier\nNew Shop,new.shop.uz,B\n"
    result = await service.import_file("competitors.csv", payload)
    assert result.created == 1
    rows = await WebQueryService(session_factory, hot_threshold=70).competitors()
    imported = next(item for item in rows if item["competitor"].normalized_handle == "new.shop.uz")
    assert imported["competitor"].active is False


async def test_competitor_import_is_idempotent(session_factory):
    service = CompetitorImportService(session_factory)
    payload = b"company,instagram\nRepeat Co,repeat.co\n"
    first = await service.import_file("competitors.csv", payload)
    second = await service.import_file("competitors.csv", payload)
    assert first.created == 1
    assert second.created == 0
    assert second.updated == 1


async def test_competitor_compare_page(session_factory):
    contacts = ContactService(session_factory)
    leads = LeadService(session_factory, StaticAnalyzer(), hot_threshold=70)
    first = await contacts.persist_signal(make_post(), make_comment("cmp-aiko"))
    other_post = make_post().model_copy(
        update={
            "platform_post_id": "cmp-chinar-post",
            "competitor": "chinar.uz",
            "url": "https://www.instagram.com/reel/cmp-chinar-post/",
        }
    )
    second = await contacts.persist_signal(
        other_post,
        make_comment("cmp-chinar").model_copy(
            update={
                "platform_user_id": "buyer-chinar-compare",
                "username": "buyer_chinar",
            }
        ),
    )
    await leads.process_signal(first)
    await leads.process_signal(second)

    queries = WebQueryService(session_factory, hot_threshold=70)
    rows = await queries.competitors()
    aiko = next(item for item in rows if item["competitor"].normalized_handle == "aiko.uz")
    chinar = next(item for item in rows if item["competitor"].normalized_handle == "chinar.uz")
    compare = await queries.competitor_compare(aiko["competitor"].id, chinar["competitor"].id)
    assert compare is not None
    assert compare["shared_buyers"] == 0
    assert len(compare["rows"]) >= 5

    settings = Settings(_env_file=None, web_enabled=True, instagram_provider="replay", web_manager_id=1001)
    app = build_web_app(
        settings,
        queries,
        LeadWorkflowService(session_factory, hot_threshold=70),
        MonitorController(None),  # type: ignore[arg-type]
        crm=CRMService(session_factory),
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            f"/competitors/compare?left={aiko['competitor'].id}&right={chinar['competitor'].id}"
        )
    assert response.status_code == 200
    assert "competitor-compare-table" in response.text


async def test_ready_endpoint_includes_extended_fields(session_factory):
    settings = Settings(_env_file=None, web_enabled=True, instagram_provider="replay")
    workflow = LeadWorkflowService(session_factory, hot_threshold=70)
    app = build_web_app(
        settings,
        WebQueryService(session_factory, hot_threshold=70),
        workflow,
        MonitorController(None),  # type: ignore[arg-type]
        crm=CRMService(session_factory),
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/ready")
    payload = response.json()
    assert response.status_code == 200
    assert "backup_present" in payload
    assert "uncertain_reservations" in payload
    assert "active_competitors" in payload
    assert "competitors_total" in payload


async def test_lead_detail_has_print_sheet(session_factory):
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
    assert "lead-print-sheet" in html
    assert 'aria-label="Печать карточки лида"' in html


async def test_competitors_import_api(session_factory):
    settings = Settings(_env_file=None, web_enabled=True, instagram_provider="replay", web_manager_id=1001)
    app = build_web_app(
        settings,
        WebQueryService(session_factory, hot_threshold=70),
        LeadWorkflowService(session_factory, hot_threshold=70),
        MonitorController(None),  # type: ignore[arg-type]
        crm=CRMService(session_factory),
    )
    payload = b"company,instagram\nApi Import,api.import.uz\n"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/competitors/import?filename=competitors.csv",
            content=payload,
            headers={"Content-Type": "application/octet-stream"},
        )
    assert response.status_code == 200
    assert response.json()["created"] == 1
