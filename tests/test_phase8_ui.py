"""Integration tests for Phase 8 system/agent/export UI."""

from __future__ import annotations

from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.services.audience_service import AudienceEngine
from app.services.crm_service import CRMService
from app.services.lead_workflow_service import LeadWorkflowService
from app.services.monitor_controller import MonitorController
from app.web.app import build_web_app
from app.web.queries import WebQueryService
from tests.test_lead_workflow import create_lead


async def test_system_page_renders_agent_and_export_workspaces(session_factory):
    await AudienceEngine(session_factory, hot_threshold=70).sync_segments()
    settings = Settings(_env_file=None, web_enabled=True, instagram_provider="replay", web_manager_id=1001)
    app = build_web_app(
        settings,
        WebQueryService(session_factory, hot_threshold=70),
        LeadWorkflowService(session_factory, hot_threshold=70),
        MonitorController(None),  # type: ignore[arg-type]
        crm=CRMService(session_factory),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/system")
        agent = await client.post(
            "/api/agent/query",
            json={"query": "Покажи лиды"},
        )

    assert response.status_code == 200
    assert "АССИСТЕНТ · ТОЛЬКО БАЗА" in response.text
    assert "Export recipes preview" in response.text or "Предпросмотр export recipes" in response.text
    assert 'id="uncertain-notifications"' in response.text
    assert 'id="quality-gates"' in response.text
    assert "b2b_horeca_wholesale" in response.text
    assert agent.status_code == 200
    assert agent.json()["grounded"] is True


async def test_lead_detail_renders_grounded_agent_panel(session_factory):
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
        agent = await client.post(
            "/api/agent/query",
            json={"query": "Объясни оценку", "lead_id": lead_id},
        )

    assert response.status_code == 200
    assert "lead-agent-panel" in response.text
    assert f'name="lead_id" value="{lead_id}"' in response.text
    assert "data-agent-query" in response.text
    assert agent.status_code == 200
    assert agent.json()["grounded"] is True
    assert agent.json()["tool_calls"][0]["tool_name"] == "lead.explain_score"


async def test_contact_detail_renders_grounded_agent_panel(session_factory):
    lead_id = await create_lead(session_factory)
    settings = Settings(_env_file=None, web_enabled=True, instagram_provider="replay", web_manager_id=1001)
    queries = WebQueryService(session_factory, hot_threshold=70)
    app = build_web_app(
        settings,
        queries,
        LeadWorkflowService(session_factory, hot_threshold=70),
        MonitorController(None),  # type: ignore[arg-type]
        crm=CRMService(session_factory),
    )
    lead_data = await queries.lead_detail(lead_id)
    assert lead_data is not None
    contact_id = lead_data["contact"].id

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/contacts/{contact_id}")
        agent = await client.post(
            "/api/agent/query",
            json={"query": "Объясни оценку", "lead_id": lead_id},
        )

    assert response.status_code == 200
    assert "lead-agent-panel" in response.text
    assert f'value="{lead_id}"' in response.text
    assert "@user-1" in response.text
    assert "contact-agent-result" in response.text
    assert "data-agent-query" in response.text
    assert agent.status_code == 200
    assert agent.json()["grounded"] is True


async def test_lead_stage_api_moves_funnel(session_factory):
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
        taken = await client.post(f"/api/leads/{lead_id}/take", json={})
        contacted = await client.post(
            f"/api/leads/{lead_id}/stage",
            json={"status": "CONTACTED"},
        )
        qualified = await client.post(
            f"/api/leads/{lead_id}/stage",
            json={"status": "QUALIFIED"},
        )

    assert taken.status_code == 200
    assert taken.json()["status"] == "TAKEN"
    assert contacted.status_code == 200
    assert contacted.json()["status"] == "CONTACTED"
    assert qualified.status_code == 200
    assert qualified.json()["status"] == "QUALIFIED"


async def test_reanalyze_batch_api(session_factory):
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
        response = await client.post("/api/leads/reanalyze-batch", json={"limit": 5})

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["processed"] >= 1
    assert "message" in body
    assert lead_id  # lead создан и должен попасть в выборку NEW

async def test_uncertain_notification_resolve_api(session_factory):
    from sqlalchemy import select

    from app.db.models import NotificationLog, NotificationStatus
    from app.services.telegram_notification_service import TelegramLeadNotifier
    from tests.test_notifications import AmbiguousBot

    lead_id = await create_lead(session_factory)
    notifier = TelegramLeadNotifier(
        AmbiguousBot(),
        session_factory,
        LeadWorkflowService(session_factory, 70),
        [1001],
        hot_threshold=70,
    )
    assert await notifier.notify_hot_lead(lead_id) == 0
    async with session_factory() as session:
        log = await session.scalar(select(NotificationLog))
        assert log is not None
        assert log.status == NotificationStatus.UNCERTAIN
        log_id = log.id

    settings = Settings(_env_file=None, web_enabled=True, instagram_provider="replay", web_manager_id=1001)
    app = build_web_app(
        settings,
        WebQueryService(session_factory, hot_threshold=70),
        LeadWorkflowService(session_factory, hot_threshold=70),
        MonitorController(None),  # type: ignore[arg-type]
        crm=CRMService(session_factory),
        notification_worker_active=True,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        system = await client.get("/system")
        resolve = await client.post(
            f"/api/notifications/uncertain/lead/{log_id}/resolve",
            json={"delivered": False},
        )
    assert system.status_code == 200
    assert "Неоднозначные Telegram-отправки" in system.text
    assert resolve.status_code == 200
    assert resolve.json()["ok"] is True
    async with session_factory() as session:
        log = await session.get(NotificationLog, log_id)
        assert log is not None
        assert log.status == NotificationStatus.PENDING
        assert log.resolution == "CONFIRMED_NOT_SENT_REQUEUED"
        assert log.uncertain_at is None
        assert log.resolved_at is not None
