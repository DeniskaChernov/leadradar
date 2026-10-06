from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.services.lead_workflow_service import LeadWorkflowService
from app.services.monitor_controller import MonitorController
from app.web.app import build_web_app
from app.web.auth import TelegramWebAuth
from app.web.queries import WebQueryService


async def test_password_login_protects_crm_and_scan_with_secure_session(session_factory):
    password = "test-password-for-browser"
    settings = Settings(
        _env_file=None,
        web_auth_enabled=True,
        telegram_bot_token="test-token",
        telegram_admin_chat_ids=[101],
        web_public_url="https://radar.example.com",
        web_password_hash=TelegramWebAuth.hash_password(password),
    )
    app = build_web_app(
        settings,
        WebQueryService(session_factory, hot_threshold=70),
        LeadWorkflowService(session_factory, hot_threshold=70),
        MonitorController(None),
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=settings.web_public_url
    ) as client:
        assert (await client.get("/api/radar/feed")).status_code == 401
        assert (await client.post("/api/scan", json={})).status_code == 401
        assert (
            await client.post(
                "/api/auth/password",
                json={"password": password},
                headers={"Origin": "https://evil.example"},
            )
        ).status_code == 403
        assert (
            await client.post("/api/auth/password", json={"password": "wrong"})
        ).status_code == 401
        response = await client.post(
            "/api/auth/password",
            json={"password": password},
            headers={"Origin": settings.web_public_url},
        )
        assert response.status_code == 200
        cookie = response.headers["set-cookie"]
        assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=strict" in cookie
        assert (await client.get("/api/radar/feed")).status_code == 200
        assert (await client.post("/api/scan", json={})).status_code == 403
        auth = TelegramWebAuth(settings)
        token = client.cookies.get(auth.COOKIE_NAME)
        logout = await client.post(
            "/logout", headers={"X-CSRF-Token": auth.create_csrf_token(token)}
        )
        assert logout.status_code == 303
        assert (await client.get("/api/radar/feed")).status_code == 401
        for _ in range(6):
            assert (
                await client.post("/api/auth/password", json={"password": "wrong"})
            ).status_code == 401
        blocked = await client.post("/api/auth/password", json={"password": password})
        assert blocked.status_code == 429
        assert int(blocked.headers["retry-after"]) > 0


def test_password_rotation_revokes_sessions_and_hashes_are_salted():
    password = "long-enough-password"
    first = TelegramWebAuth.hash_password(password)
    assert first != TelegramWebAuth.hash_password(password)
    settings = Settings(
        _env_file=None,
        web_auth_enabled=True,
        telegram_bot_token="test-token",
        telegram_admin_chat_ids=[101],
        web_password_hash=first,
    )
    auth = TelegramWebAuth(settings)
    token = auth.create_session(101)
    assert auth.validate_password(password)
    assert not auth.validate_password("bad-password")
    assert not auth.validate_password("x" * 257)
    settings.web_password_hash = TelegramWebAuth.hash_password("replacement-password")
    assert auth.validate_session(token) is None


async def test_password_login_disabled_by_default(session_factory):
    settings = Settings(
        _env_file=None,
        web_auth_enabled=True,
        telegram_bot_token="test-token",
        telegram_admin_chat_ids=[101],
    )
    app = build_web_app(
        settings,
        WebQueryService(session_factory, hot_threshold=70),
        LeadWorkflowService(session_factory, hot_threshold=70),
        MonitorController(None),
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        assert (
            await client.post("/api/auth/password", json={"password": "anything"})
        ).status_code == 404
