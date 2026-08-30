"""Fail-closed проверка offline/live готовности без внешних вызовов."""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import func, select, text

from alembic import command

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import Settings, get_settings  # noqa: E402
from app.db.models import ExternalBudgetReservation, ReservationStatus  # noqa: E402
from app.db.session import create_engine  # noqa: E402


@dataclass(frozen=True, slots=True)
class LocalReadinessState:
    database_healthy: bool
    database_error: str | None
    migration_at_head: bool
    migration_drift_free: bool
    migration_error: str | None
    backup_present: bool
    uncertain_reservations: int


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
    engine = create_engine(settings)
    database_healthy = False
    database_error: str | None = None
    migration_at_head = False
    migration_error: str | None = None
    uncertain_reservations = 0
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
            database_healthy = True

            def revision_state(sync_connection) -> tuple[str | None, tuple[str, ...]]:
                config = _alembic_config()
                current = MigrationContext.configure(sync_connection).get_current_revision()
                heads = tuple(ScriptDirectory.from_config(config).get_heads())
                return current, heads

            current, heads = await connection.run_sync(revision_state)
            migration_at_head = current is not None and len(heads) == 1 and current == heads[0]
            if not migration_at_head:
                migration_error = f"current={current or 'none'}, heads={','.join(heads) or 'none'}"

            uncertain_reservations = int(
                await connection.scalar(
                    select(func.count(ExternalBudgetReservation.id)).where(
                        ExternalBudgetReservation.status == ReservationStatus.UNCERTAIN
                    )
                )
                or 0
            )
    except Exception as exc:
        database_error = f"{type(exc).__name__}: {exc}"
    finally:
        await engine.dispose()

    migration_drift_free = False
    if database_healthy and migration_at_head:
        try:
            await asyncio.to_thread(command.check, _alembic_config())
            migration_drift_free = True
        except Exception as exc:
            migration_error = f"{type(exc).__name__}: {exc}"

    return LocalReadinessState(
        database_healthy=database_healthy,
        database_error=database_error,
        migration_at_head=migration_at_head,
        migration_drift_free=migration_drift_free,
        migration_error=migration_error,
        backup_present=_backup_present(settings),
        uncertain_reservations=uncertain_reservations,
    )


def _alembic_config() -> Config:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    return config


def _backup_present(settings: Settings) -> bool:
    if not settings.database_url.startswith("sqlite"):
        return True
    backups = (PROJECT_ROOT / ".backups").glob("*.db")
    return any(path.is_file() and path.stat().st_size > 0 for path in backups)


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
