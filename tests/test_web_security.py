from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from app.config import Settings
from app.services.instagram_monitor import CycleStats
from app.services.lead_workflow_service import LeadWorkflowService
from app.services.monitor_controller import MonitorController
from app.web.app import build_web_app
from app.web.auth import TelegramAuthError, TelegramWebAuth, WebRole, required_role
from app.web.queries import WebQueryService


class FakeMonitor:
    provider = None

    async def run_cycle(self, *, force: bool = True) -> CycleStats:
        return CycleStats()


def _secured_settings() -> Settings:
    return Settings(
        _env_file=None,
        telegram_bot_token="test-token",
        telegram_admin_chat_ids=[101],
        telegram_manager_chat_ids=[202],
        telegram_viewer_chat_ids=[303],
        web_auth_enabled=True,
    )


def _telegram_init_data(token: str, user_id: int, auth_date: int) -> str:
    fields = {
        "auth_date": str(auth_date),
        "query_id": "test-query",
        "user": json.dumps(
            {"id": user_id, "first_name": "Test"},
            separators=(",", ":"),
        ),
    }
    data_check_string = "\n".join(f"{key}={fields[key]}" for key in sorted(fields))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(
        secret,
        data_check_string.encode(),
        hashlib.sha256,
    ).hexdigest()
    return urlencode(fields)


def test_public_web_configuration_is_fail_closed():
    with pytest.raises(ValidationError, match="WEB_AUTH_ENABLED"):
        Settings(_env_file=None, web_host="0.0.0.0")

    with pytest.raises(ValidationError, match="HTTPS"):
        Settings(
            _env_file=None,
            web_host="0.0.0.0",
            web_auth_enabled=True,
            telegram_bot_token="test-token",
            telegram_admin_chat_ids=[101],
        )

    settings = Settings(
        _env_file=None,
        web_host="0.0.0.0",
        web_public_url="https://lead-radar.example",
        web_auth_enabled=True,
        telegram_bot_token="test-token",
        telegram_admin_chat_ids=[101],
    )
    assert settings.web_auth_enabled is True


def test_authenticated_web_requires_unique_role_allowlist():
    with pytest.raises(ValidationError, match="TELEGRAM_BOT_TOKEN"):
        Settings(_env_file=None, web_auth_enabled=True, telegram_admin_chat_ids=[101])

    with pytest.raises(ValidationError, match="at least one allowed Telegram ID"):
        Settings(
            _env_file=None,
            web_auth_enabled=True,
            telegram_bot_token="test-token",
        )

    with pytest.raises(ValidationError, match="exactly one web role"):
        Settings(
            _env_file=None,
            web_auth_enabled=True,
            telegram_bot_token="test-token",
            telegram_admin_chat_ids=[101],
            telegram_manager_chat_ids=[101],
        )


def test_role_policy_separates_read_crm_and_system_actions():
    assert required_role("GET", "/api/scan/preview") is WebRole.VIEWER
    assert required_role("POST", "/api/contacts/1/notes") is WebRole.MANAGER
    assert required_role("POST", "/api/catalog/1") is WebRole.ADMIN
    assert required_role("POST", "/logout") is WebRole.VIEWER


def test_telegram_init_data_accepts_allowlisted_roles_and_rejects_stale_or_unknown():
    settings = _secured_settings()
    auth = TelegramWebAuth(settings)
    now = int(time.time())

    assert auth.validate_init_data(
        _telegram_init_data(settings.telegram_bot_token, 202, now)
    ).id == 202

    with pytest.raises(TelegramAuthError, match="нет доступа"):
        auth.validate_init_data(
            _telegram_init_data(settings.telegram_bot_token, 999, now)
        )

    with pytest.raises(TelegramAuthError, match="too old"):
        auth.validate_init_data(
            _telegram_init_data(
                settings.telegram_bot_token,
                202,
                now - settings.telegram_init_data_max_age_seconds - 1,
            )
        )


async def test_session_role_csrf_and_revocation_are_enforced(session_factory):
    settings = _secured_settings()
    auth = TelegramWebAuth(settings)
    workflow = LeadWorkflowService(session_factory, hot_threshold=70)
    app = build_web_app(
        settings,
        WebQueryService(session_factory, hot_threshold=70),
        workflow,
        MonitorController(FakeMonitor()),  # type: ignore[arg-type]
    )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        health = await client.get("/health")
    assert health.status_code == 200
    assert health.headers["x-content-type-options"] == "nosniff"
    assert health.headers["cache-control"] == "no-store"
    assert "object-src 'none'" in health.headers["content-security-policy"]

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://untrusted.example",
    ) as client:
        untrusted_host = await client.get("/health")
    assert untrusted_host.status_code == 400

    async def post_as(user_id: int, path: str, *, include_csrf: bool = True):
        session_token = auth.create_session(user_id)
        headers = {}
        if include_csrf:
            headers["X-CSRF-Token"] = auth.create_csrf_token(session_token)
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
            cookies={auth.COOKIE_NAME: session_token},
        ) as client:
            return await client.post(path, json={}, headers=headers)

    missing_csrf = await post_as(101, "/api/replay/reset", include_csrf=False)
    assert missing_csrf.status_code == 403
    assert "CSRF" in missing_csrf.json()["detail"]

    viewer_write = await post_as(303, "/api/contacts/999/notes")
    assert viewer_write.status_code == 403
    assert "Недостаточно прав" in viewer_write.json()["detail"]

    manager_admin_action = await post_as(202, "/api/replay/reset")
    assert manager_admin_action.status_code == 403

    manager_crm_action = await post_as(202, "/api/contacts/999/notes")
    assert manager_crm_action.status_code == 400
    assert "Недостаточно прав" not in manager_crm_action.json()["detail"]

    admin_action = await post_as(101, "/api/replay/reset")
    assert admin_action.status_code == 409
    assert "Replay-режим" in admin_action.json()["detail"]

    assert auth.validate_session(auth.create_session(101)) == 101
    settings.telegram_admin_chat_ids.clear()
    assert auth.validate_session(auth.create_session(101)) is None
