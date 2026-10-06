"""Configure browser access locally; never print the generated password."""

from __future__ import annotations

import argparse
import secrets
from pathlib import Path
from urllib.parse import urlparse

from dotenv import dotenv_values, set_key

from app.config import Settings
from app.web.auth import TelegramWebAuth


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--public-url", default="")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    env = root / ".env"
    values = dotenv_values(env)
    if args.public_url:
        parsed = urlparse(args.public_url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.path not in {"", "/"}:
            raise SystemExit("An HTTPS origin URL is required")
    # Validate existing admin identity before changing configuration.
    settings = Settings(_env_file=env)
    if not settings.telegram_admin_chat_ids or not settings.telegram_bot_token:
        raise SystemExit("Configure TELEGRAM_BOT_TOKEN and an admin ID first")
    runtime = root / ".runtime"
    runtime.mkdir(exist_ok=True)
    if not values.get("WEB_PASSWORD_HASH"):
        password = secrets.token_urlsafe(24)
        access_file = runtime / "web-access.txt"
        with access_file.open("x", encoding="utf-8") as handle:
            handle.write(
                "Lead Radar — пароль доступа\n"
                + password
                + "\n\nХраните этот файл локально. Не публикуйте его.\n"
            )
        set_key(str(env), "WEB_PASSWORD_HASH", TelegramWebAuth.hash_password(password))
    set_key(str(env), "WEB_AUTH_ENABLED", "true")
    if args.public_url:
        set_key(str(env), "WEB_PUBLIC_URL", args.public_url.rstrip("/"))
    Settings(_env_file=env)
    print("Browser access configured. Local password file: .runtime/web-access.txt")


if __name__ == "__main__":
    main()
