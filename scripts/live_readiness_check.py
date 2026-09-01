"""Fail-closed проверка offline/live готовности без внешних вызовов."""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import Settings, get_settings  # noqa: E402
from app.services.deployment_readiness_service import (  # noqa: E402
    OfflineReadinessState as LocalReadinessState,
    inspect_offline_readiness,
)


@dataclass(frozen=True, slots=True)
class ReadinessReport:
    offline_blocks: tuple[str, ...]
    live_blocks: tuple[str, ...]

    @property
    def offline_ready(self) -> bool:
        return not self.offline_blocks

    @property
    def live_ready(self) -> bool:
        return self.offline_ready and not self.live_blocks


def evaluate_readiness(
    settings: Settings,
    state: LocalReadinessState,
) -> ReadinessReport:
    """Разделить offline/live готовность; обязательные live-условия всегда блокируют."""
    offline_blocks: list[str] = []
    live_blocks: list[str] = []

    if not state.database_healthy:
        offline_blocks.append(f"Database health failed: {state.database_error or 'unknown error'}")
    if not state.migration_at_head:
        offline_blocks.append(
            f"Database migration is not at Alembic head: {state.migration_error or 'unknown revision'}"
        )
    if not state.migration_drift_free:
        offline_blocks.append(
            f"ORM metadata has migration drift: {state.migration_error or 'alembic check failed'}"
        )

    if not settings.external_spend_unlocked:
        live_blocks.append(
            "External live unlock is missing. EXTERNAL_KILL_SWITCH must be false and "
            "EXTERNAL_LIVE_UNLOCK must equal ALLOW_EXTERNAL_CALLS."
        )
    if not settings.instagram_live_enabled:
        live_blocks.append("Instagram live calls are disabled by configuration.")
    if settings.instagram_provider not in {"scrapecreators", "brightdata"}:
        live_blocks.append(
            "A live provider is not selected; INSTAGRAM_PROVIDER must be scrapecreators or brightdata."
        )
    elif settings.instagram_provider == "scrapecreators" and not settings.scrapecreators_api_key:
        live_blocks.append("SCRAPECREATORS_API_KEY is missing for the configured live provider.")
    elif settings.instagram_provider == "brightdata" and not settings.brightdata_api_key:
        live_blocks.append("BRIGHTDATA_API_KEY is missing for the configured live provider.")

    if settings.ai_mode in {"hybrid", "openai"}:
        if not settings.openai_live_enabled:
            live_blocks.append("OpenAI live calls are disabled for the configured AI mode.")
        if not settings.openai_api_key:
            live_blocks.append("OPENAI_API_KEY is missing for the configured AI mode.")
        if settings.openai_daily_request_limit <= 0:
            live_blocks.append("OpenAI daily request limit must be positive for a live pilot.")

    if not settings.telegram_bot_token:
        live_blocks.append("TELEGRAM_BOT_TOKEN is missing.")
    if not settings.telegram_admin_chat_ids:
        live_blocks.append("At least one Telegram admin ID is required for a controlled pilot.")
    if not state.backup_present:
        live_blocks.append("A non-empty SQLite backup is required before live operation.")
    if state.uncertain_reservations:
        live_blocks.append(
            f"{state.uncertain_reservations} unresolved UNCERTAIN external reservation(s) exist."
        )

    return ReadinessReport(tuple(offline_blocks), tuple(live_blocks))


async def inspect_local_state(settings: Settings) -> LocalReadinessState:
    """Проверить БД, ревизию и неопределённые расходы без обращения к провайдерам."""
    return await inspect_offline_readiness(settings)


def main() -> None:
    print("==================================================")
    print("       LEAD RADAR V6 — LIVE READINESS CHECK       ")
    print("==================================================")

    settings = get_settings()
    state = asyncio.run(inspect_local_state(settings))
    report = evaluate_readiness(settings, state)

    print(f"[{'OK' if state.database_healthy else 'X'}] Database health")
    print(f"[{'OK' if state.migration_at_head else 'X'}] Database at Alembic head")
    print(f"[{'OK' if state.migration_drift_free else 'X'}] Alembic metadata drift check")
    print(f"[{'OK' if state.backup_present else 'X'}] Backup present")
    print(f"[{'OK' if not state.uncertain_reservations else 'X'}] Unresolved UNCERTAIN reservations: {state.uncertain_reservations}")

    print("\n--------------------------------------------------")
    if report.offline_ready:
        print("STATUS: READY FOR OFFLINE USE")
    else:
        print("STATUS: OFFLINE BLOCKED")
        for block in report.offline_blocks:
            print(f"  [X] {block}")

    if report.live_ready:
        print("STATUS: READY FOR LIVE PILOT")
    else:
        print("STATUS: LIVE BLOCKED")
        for block in (*report.offline_blocks, *report.live_blocks):
            print(f"  [X] {block}")
    print("--------------------------------------------------")
    sys.exit(0 if report.live_ready else 1)



if __name__ == "__main__":
    main()
