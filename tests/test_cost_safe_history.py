from __future__ import annotations

from datetime import UTC, datetime

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.config import Settings
from app.db.models import Lead, LeadStatus
from app.providers.mock import MockInstagramProvider
from app.schemas.instagram import InstagramComment
from app.services.contact_service import ContactService
from app.services.lead_workflow_service import LeadWorkflowService
from app.services.monitor_controller import MonitorController
from app.services.usage_service import ExternalUsageService
from app.web.app import build_web_app
from app.web.queries import WebQueryService


class FakeMonitor:
    provider = None


async def test_local_history_analysis_never_calls_openai_and_keeps_ambiguous_pending(session_factory):
    provider = MockInstagramProvider()
    ambiguous = InstagramComment(
        platform_comment_id="ambiguous-1",
        platform_user_id="ambiguous-user-1",
        username="maybe_customer",
        display_name="Maybe Customer",
        profile_url="https://www.instagram.com/maybe_customer/",
        text="А это как вообще работает?",
        created_at=datetime(2026, 8, 26, 12, 0, tzinfo=UTC),
        raw_data={"source": "test"},
    )
    await ContactService(session_factory).persist_signal(
        provider._post,
        ambiguous,
        is_baseline=True,
    )

    # Even with every live switch enabled, the Mini App's local-history action must remain local.
    settings = Settings(
        _env_file=None,
        openai_api_key="would-be-paid-key",
        openai_live_calls_enabled=True,
        external_live_unlock="ALLOW_EXTERNAL_CALLS",
        web_enabled=True,
    )
    controller = MonitorController(FakeMonitor())  # type: ignore[arg-type]
    app = build_web_app(
        settings,
        WebQueryService(session_factory, hot_threshold=70),
        LeadWorkflowService(session_factory, hot_threshold=70),
        controller,
        ExternalUsageService(session_factory),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/history/analyze-local", json={"limit": 10})

    assert response.status_code == 200
    payload = response.json()
    assert payload["processed"] == 1
    assert payload["pending"] == 1
    assert "OpenAI не вызывался" in payload["message"]

    async with session_factory() as session:
        lead = await session.scalar(select(Lead).where(Lead.comment_id.is_not(None)))
        assert lead is not None
        assert lead.status == LeadStatus.AI_PENDING



def test_external_unlock_is_required_in_addition_to_live_switches():
    locked = Settings(
        _env_file=None,
        instagram_live_calls_enabled=True,
        openai_live_calls_enabled=True,
        external_live_unlock="",
    )
    assert locked.instagram_live_enabled is False
    assert locked.openai_live_enabled is False

    unlocked = Settings(
        _env_file=None,
        instagram_live_calls_enabled=True,
        openai_live_calls_enabled=True,
        external_live_unlock="ALLOW_EXTERNAL_CALLS",
    )
    assert unlocked.instagram_live_enabled is True
    assert unlocked.openai_live_enabled is True
