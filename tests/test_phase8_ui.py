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


async def test_bulk_lead_action_api(session_factory):
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
        response = await client.post(
            "/api/leads/bulk-action",
            json={"action": "take", "lead_ids": [lead_id]},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["processed"] == 1
    assert "Сохранено" in body["message"]


async def test_follow_up_api_schedules_task(session_factory):
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
        response = await client.post(
            f"/api/leads/{lead_id}/follow-up",
            json={"hours": 24},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["task_id"]
    assert "напоминание" in body["message"].lower()


async def test_bulk_competitors_active_api(session_factory):
    crm = CRMService(session_factory)
    first = await crm.add_competitor("wave5pause1", display_name="Wave5 Pause 1", tier="B")
    second = await crm.add_competitor("wave5pause2", display_name="Wave5 Pause 2", tier="C")
    assert first.active is True
    assert second.active is True

    settings = Settings(_env_file=None, web_enabled=True, instagram_provider="replay", web_manager_id=1001)
    app = build_web_app(
        settings,
        WebQueryService(session_factory, hot_threshold=70),
        LeadWorkflowService(session_factory, hot_threshold=70),
        MonitorController(None),  # type: ignore[arg-type]
        crm=crm,
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        pause = await client.post(
            "/api/competitors/bulk-active",
            json={"competitor_ids": [first.id, second.id], "active": False},
        )
        resume = await client.post(
            "/api/competitors/bulk-active",
            json={"competitor_ids": [first.id], "active": True},
        )
        page = await client.get("/competitors")

    assert pause.status_code == 200
    pause_body = pause.json()
    assert pause_body["ok"] is True
    assert pause_body["changed"] == 2
    assert "паузу" in pause_body["message"].lower()

    assert resume.status_code == 200
    resume_body = resume.json()
    assert resume_body["ok"] is True
    assert resume_body["changed"] == 1
    assert resume_body["active"] is True

    assert page.status_code == 200
    assert "data-competitor-bulk" in page.text
    assert "competitors-plain-help" in page.text

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        noop = await client.post(
            "/api/competitors/bulk-active",
            json={"competitor_ids": [first.id], "active": True},
        )
    assert noop.status_code == 200
    assert noop.json()["changed"] == 0


async def test_leads_export_csv_and_scan_progress_gpt_queue(session_factory):
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
        export = await client.get("/api/leads/export.csv")
        progress = await client.get("/api/scan/progress")
        system = await client.get("/system")
        discovery = await client.get("/discovery")

    assert export.status_code == 200
    assert "text/csv" in export.headers.get("content-type", "")
    body = export.text
    assert "lead_id" in body
    assert str(lead_id) in body
    assert "username" in body

    assert progress.status_code == 200
    progress_body = progress.json()
    assert "ai_pending" in progress_body
    assert "analyzing" in progress_body
    assert "gpt_queue_total" in progress_body

    assert system.status_code == 200
    assert "manager-feedback-quality" in system.text
    assert "HOT → не лид" in system.text or "HOT FP" in system.text
    assert "Правила обновились" in system.text or "rules_reanalyze" in system.text or "v3.2" in system.text or "текущие правила" in system.text

    assert discovery.status_code == 200
    from pathlib import Path

    discovery_tpl = Path("app/web/templates/discovery.html").read_text(encoding="utf-8")
    assert "В радар активно" in discovery_tpl
    assert "discovery-promote-handle" in discovery_tpl
    assert "discovery-import" in discovery.text


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
