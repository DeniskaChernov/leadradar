from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from enum import IntEnum
from urllib.parse import parse_qsl

from app.config import Settings


class TelegramAuthError(RuntimeError):
    pass


class WebRole(IntEnum):
    VIEWER = 10
    MANAGER = 20
    ADMIN = 30


@dataclass(frozen=True, slots=True)
class WebPrincipal:
    user_id: int
    role: WebRole


@dataclass(frozen=True, slots=True)
class TelegramUser:
    id: int
    first_name: str
    last_name: str | None = None
    username: str | None = None


class TelegramWebAuth:
    COOKIE_NAME = "lr_session"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def principal_for(self, user_id: int) -> WebPrincipal | None:
        if user_id in self.settings.telegram_admin_chat_ids:
            return WebPrincipal(user_id=user_id, role=WebRole.ADMIN)
        if user_id in self.settings.telegram_manager_chat_ids:
            return WebPrincipal(user_id=user_id, role=WebRole.MANAGER)
        if user_id in self.settings.telegram_viewer_chat_ids:
            return WebPrincipal(user_id=user_id, role=WebRole.VIEWER)
        return None

    def validate_init_data(self, init_data: str) -> TelegramUser:
        if not self.settings.telegram_bot_token:
            raise TelegramAuthError("Telegram bot token is not configured")
        pairs = dict(parse_qsl(init_data, keep_blank_values=True))
        received_hash = pairs.pop("hash", "")
        if not received_hash:
            raise TelegramAuthError("Telegram initData has no hash")
        pairs.pop("signature", None)
        data_check_string = "\n".join(f"{key}={pairs[key]}" for key in sorted(pairs))
        secret_key = hmac.new(
            b"WebAppData",
            self.settings.telegram_bot_token.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        calculated = hmac.new(
            secret_key,
            data_check_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(calculated, received_hash):
            raise TelegramAuthError("Telegram signature is invalid")
        try:
            auth_date = int(pairs.get("auth_date", "0"))
        except ValueError as exc:
            raise TelegramAuthError("Telegram auth_date is invalid") from exc
        if auth_date <= 0 or abs(int(time.time()) - auth_date) > self.settings.telegram_init_data_max_age_seconds:
            raise TelegramAuthError("Telegram session is too old")
        try:
            user_data = json.loads(pairs.get("user", "{}"))
            user_id = int(user_data["id"])
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise TelegramAuthError("Telegram user data is invalid") from exc
        configured_ids = (
            set(self.settings.telegram_admin_chat_ids)
            | set(self.settings.telegram_manager_chat_ids)
            | set(self.settings.telegram_viewer_chat_ids)
        )
        if configured_ids and user_id not in configured_ids:
            raise TelegramAuthError("У этого Telegram-пользователя нет доступа к Lead Radar")
        return TelegramUser(
            id=user_id,
            first_name=str(user_data.get("first_name") or "Менеджер"),
            last_name=user_data.get("last_name"),
            username=user_data.get("username"),
        )

    def create_session(self, user_id: int, ttl_seconds: int = 7 * 86400) -> str:
        expires = int(time.time()) + ttl_seconds
        payload = f"{user_id}.{expires}"
        signature = hmac.new(self._session_key(), payload.encode(), hashlib.sha256).hexdigest()
        return f"{payload}.{signature}"

    def validate_session(self, token: str | None) -> int | None:
        if not token:
            return None
        try:
            user_raw, expires_raw, signature = token.split(".", 2)
            user_id = int(user_raw)
            expires = int(expires_raw)
        except (ValueError, TypeError):
            return None
        if expires < int(time.time()):
            return None
        payload = f"{user_id}.{expires}"
        expected = hmac.new(self._session_key(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            return None
        if self.settings.web_auth_enabled and self.principal_for(user_id) is None:
            return None
        return user_id

    def create_csrf_token(self, session_token: str) -> str:
        return hmac.new(
            self._session_key(),
            f"csrf:{session_token}".encode(),
            hashlib.sha256,
        ).hexdigest()

    def validate_csrf_token(self, session_token: str, csrf_token: str | None) -> bool:
        if not csrf_token:
            return False
        expected = self.create_csrf_token(session_token)
        return hmac.compare_digest(expected, csrf_token)

    def _session_key(self) -> bytes:
        if not self.settings.telegram_bot_token:
            raise TelegramAuthError("Telegram bot token is required for signed web sessions")
        return hashlib.sha256(
            f"lead-radar:{self.settings.telegram_bot_token}".encode()
        ).digest()


_ADMIN_PATH_PREFIXES = (
    "/api/pricing",
    "/api/replay/",
    "/api/scan",
    "/api/ops/",
    "/api/history/",
    "/api/audiences/export-recipes/",
    "/api/competitors",
    "/api/market-",
    "/api/discovery/",
    "/api/catalog/",
    "/api/agent/",
)


def required_role(method: str, path: str) -> WebRole:
    if method.upper() in {"GET", "HEAD", "OPTIONS"} or path == "/logout":
        return WebRole.VIEWER
    if any(path == prefix or path.startswith(prefix) for prefix in _ADMIN_PATH_PREFIXES):
        return WebRole.ADMIN
    return WebRole.MANAGER
