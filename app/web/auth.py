from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl

from app.config import Settings


class TelegramAuthError(RuntimeError):
    pass


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
        if self.settings.telegram_admin_chat_ids and user_id not in self.settings.telegram_admin_chat_ids:
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
        if self.settings.telegram_admin_chat_ids and user_id not in self.settings.telegram_admin_chat_ids:
            return None
        return user_id

    def _session_key(self) -> bytes:
        source = self.settings.telegram_bot_token or "lead-radar-local-session"
        return hashlib.sha256(f"lead-radar:{source}".encode()).digest()
