"""Общий ASGI-приложение для e2e (HTTP smoke и Playwright)."""

from __future__ import annotations

from app.config import Settings
from app.services.crm_service import CRMService
from app.services.lead_workflow_service import LeadWorkflowService
from app.services.monitor_controller import MonitorController
from app.web.app import build_web_app
from app.web.queries import WebQueryService


def build_e2e_app(session_factory):
    """Dev web без Telegram auth: WEB_MANAGER_ID задан, внешние live-гейты закрыты правилами Settings."""
    return build_web_app(
        Settings(
            _env_file=None,
            web_enabled=True,
            web_auth_enabled=False,
            web_manager_id=1001,
            instagram_provider="replay",
            openai_live_calls_enabled=False,
            external_kill_switch=True,
            openai_api_key="test-key",
        ),
        WebQueryService(session_factory, hot_threshold=70),
        LeadWorkflowService(session_factory, hot_threshold=70),
        MonitorController(None),  # type: ignore[arg-type]
        crm=CRMService(session_factory),
    )
