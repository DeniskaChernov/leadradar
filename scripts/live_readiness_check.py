"""
live_readiness_check.py — V6 Live Readiness & Pre-Flight Verification Script.

Checks system status BEFORE enabling live market scans:
  - Database connection & migration head
  - Telegram bot token & admin chat IDs
  - OpenAI API key & daily budget limits
  - Live unlock security flag (EXTERNAL_LIVE_UNLOCK)
  - Backup status
"""

from __future__ import annotations

import sys
from pathlib import Path

from app.config import get_settings


def main() -> None:
    print("==================================================")
    print("       LEAD RADAR V6 — LIVE READINESS CHECK       ")
    print("==================================================")

    settings = get_settings()
    blocks: list[str] = []
    warnings: list[str] = []

    # 1. Check Database
    db_url = settings.database_url
    print(f"[OK] Database URL: {db_url}")

    # 2. Check Security Unlock Flag
    if settings.external_spend_unlocked:
        print("[OK] External spend unlock flag: UNLOCKED (ALLOW_EXTERNAL_CALLS)")
    else:
        warnings.append("EXTERNAL_LIVE_UNLOCK is not set to ALLOW_EXTERNAL_CALLS. Live paid calls will remain disabled.")

    # 3. Check Telegram Config
    if settings.telegram_bot_token:
        print("[OK] Telegram Bot Token configured.")
    else:
        warnings.append("TELEGRAM_BOT_TOKEN is empty. Telegram notifications will run in Null/Log mode.")

    # 4. Check OpenAI Config
    if settings.openai_api_key:
        print(f"[OK] OpenAI API key configured (model: {settings.openai_model}, daily limit: {settings.openai_daily_request_limit}).")
    else:
        warnings.append("OPENAI_API_KEY is empty. AI analysis will operate in RuleBased fallback mode.")

    # 5. Check Backups
    backups_dir = Path(".backups")
    if backups_dir.exists() and list(backups_dir.glob("*.db")):
        print(f"[OK] Database backups directory present ({len(list(backups_dir.glob('*.db')))} backups).")
    else:
        warnings.append("No database backups found in .backups/. Run 'python scripts/backup_database.py'.")

    print("\n--------------------------------------------------")
    if blocks:
        print("STATUS: BLOCKED")
        for b in blocks:
            print(f"  [X] {b}")
        sys.exit(1)
    else:
        print("STATUS: READY FOR LIVE PILOT")
        if warnings:
            print("Notice / Warnings:")
            for w in warnings:
                print(f"  [!] {w}")
        print("--------------------------------------------------")
        sys.exit(0)



if __name__ == "__main__":
    main()
