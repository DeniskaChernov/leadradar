import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from app.config import Settings
from app.web.auth import TelegramAuthError, TelegramWebAuth
from tests.test_web_security import _build_test_app


def secured(**overrides):
    values = dict(web_auth_enabled=True, telegram_admin_chat_ids=[101],
                  web_session_secret="test-web-only-secret-" * 3)
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_web_only_sessions_require_strong_secret_and_do_not_enable_telegram_auth():
    with pytest.raises(ValidationError, match="WEB_SESSION_SECRET"):
        secured(web_session_secret="short")
    with pytest.raises(ValidationError, match="requires TELEGRAM_BOT_TOKEN"):
        secured(web_session_secret="")
    auth = TelegramWebAuth(secured())
    token = auth.create_session(101)
    assert auth.validate_session(token) == 101
    assert auth.validate_csrf_token(token, auth.create_csrf_token(token))
    assert auth.validate_session(token + "x") is None
    with pytest.raises(TelegramAuthError, match="not configured"):
        auth.validate_init_data("not-real-init-data")


def test_secret_rotation_and_password_change_revoke_sessions():
    initial = TelegramWebAuth(secured())
    token = initial.create_session(101)
    assert TelegramWebAuth(secured(web_session_secret="another-secret-" * 3)).validate_session(token) is None
    assert TelegramWebAuth(secured(web_password_hash=TelegramWebAuth.hash_password("new-password-2026"))).validate_session(token) is None


@pytest.mark.asyncio
async def test_password_login_csrf_and_protected_pages_without_bot_token(session_factory):
    password = "staging-password-2026"
    settings = secured(web_password_hash=TelegramWebAuth.hash_password(password))
    app = _build_test_app(settings, session_factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        assert (await client.get("/api/agent/sessions")).status_code == 401
        wrong = await client.post("/api/auth/password", json={"password": "wrong-password"})
        assert wrong.status_code == 401
        result = await client.post("/api/auth/password", json={"password": password})
        assert result.status_code == 200
        assert "httponly" in result.headers["set-cookie"].lower()
        assert (await client.get("/hot")).status_code == 200
        assert (await client.post("/api/replay/reset", json={})).status_code == 403
