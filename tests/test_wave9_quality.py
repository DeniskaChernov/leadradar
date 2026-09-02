import warnings
from datetime import UTC, datetime

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import SAWarning

from app.config import Settings
from app.db.models import AIFeedback, Lead, LeadStatus
from app.services.crm_service import CRMService
from app.services.feedback_learning_service import FeedbackLearningService
from app.services.lead_service import LeadService
from app.services.lead_workflow_service import LeadWorkflowService
from app.services.monitor_controller import MonitorController
from app.services.quality_report_service import QualityReportService
from app.web.app import build_web_app
from app.web.queries import WebQueryService
from tests.test_lead_service import StaticAnalyzer
from tests.test_lead_workflow import create_lead


async def test_feedback_learning_snapshot_and_export(session_factory):
    lead_id = await create_lead(session_factory)
    async with session_factory() as session:
        feedback = await session.scalar(select(AIFeedback).where(AIFeedback.lead_id == lead_id))
        assert feedback is not None
        feedback.manager_is_lead = False
        feedback.predicted_score = 88
        feedback.updated_at = datetime.now(UTC)
        await session.commit()

    service = FeedbackLearningService(session_factory, hot_threshold=70)
    snapshot = await service.snapshot(days=30)
    assert snapshot["hot_false_positives"] >= 1
    cases = await service.export_cases(limit=5, days=30)
    assert cases
    assert cases[0]["lead_id"] == lead_id


async def test_quality_report_service_builds_snapshot(session_factory):
    await create_lead(session_factory)
    service = QualityReportService(
        session_factory,
        hot_threshold=70,
        rules_version="3.2",
    )
    with warnings.catch_warnings():
        warnings.simplefilter("error", SAWarning)
        snapshot = await service.build_snapshot(timezone_name="UTC")
    assert snapshot.new_leads >= 1
    message = QualityReportService.format_message(snapshot, rules_version="3.2")
    assert "Lead Radar" in message
    assert "3.2" in message


async def test_reanalyze_not_lead_high_score_api(session_factory):
    lead_id = await create_lead(session_factory)
    async with session_factory() as session:
        lead = await session.get(Lead, lead_id)
        assert lead is not None
        lead.status = LeadStatus.NOT_LEAD
        lead.lead_score = 72
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
        skipped = await client.post("/api/leads/reanalyze-batch", json={"limit": 5})
        assert skipped.status_code == 200
        assert skipped.json()["processed"] == 0

        included = await client.post(
            "/api/leads/reanalyze-batch",
            json={"limit": 5, "include_not_lead_high_score": True, "min_not_lead_score": 50},
        )

    assert included.status_code == 200
    body = included.json()
    assert body["ok"] is True
    assert body["processed"] >= 1
    assert body["include_not_lead_high_score"] is True
    assert "NOT_LEAD" in body["message"]


async def test_feedback_export_api(session_factory):
    lead_id = await create_lead(session_factory)
    async with session_factory() as session:
        feedback = await session.scalar(select(AIFeedback).where(AIFeedback.lead_id == lead_id))
        assert feedback is not None
        feedback.manager_is_lead = False
        feedback.predicted_score = 91
        feedback.updated_at = datetime.now(UTC)
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
        response = await client.get("/api/system/feedback-export")

    assert response.status_code == 200
    body = response.json()
    assert body["rules_version"]
    assert any(case["lead_id"] == lead_id for case in body["cases"])


async def test_list_reanalyze_lead_ids_not_lead_filter(session_factory):
    lead_id = await create_lead(session_factory)
    async with session_factory() as session:
        lead = await session.get(Lead, lead_id)
        assert lead is not None
        lead.status = LeadStatus.NOT_LEAD
        lead.lead_score = 55
        await session.commit()

    service = LeadService(session_factory, StaticAnalyzer(), hot_threshold=70)
    default_ids = await service.list_reanalyze_lead_ids(10)
    assert lead_id not in default_ids

    included = await service.list_reanalyze_lead_ids(
        10,
        include_not_lead_high_score=True,
        min_not_lead_score=50,
    )
    assert lead_id in included

    excluded = await service.list_reanalyze_lead_ids(
        10,
        include_not_lead_high_score=True,
        min_not_lead_score=60,
    )
    assert lead_id not in excluded
