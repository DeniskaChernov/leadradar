from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import text

from app.config import Settings, get_settings
from app.db.session import create_engine, create_session_factory
from app.providers.base import ProviderUsageBlockedError
from app.providers.budgeted import BudgetedInstagramProvider, ScanBudget
from app.services.operational_control_service import OperationalControlService
from app.services.usage_service import ExternalUsageService


class CheckStatus(StrEnum):
    OK = "OK"
    SKIP = "SKIP"
    FAIL = "FAIL"


@dataclass(frozen=True, slots=True)
class CheckResult:
    name: str
    status: CheckStatus
    details: str


async def check_database(settings: Settings) -> CheckResult:
    engine = create_engine(settings)
    try:
        async with engine.connect() as connection:
            value = await connection.scalar(text("SELECT 1"))
        if value != 1:
            raise RuntimeError("Unexpected SELECT 1 result")
        return CheckResult("База данных", CheckStatus.OK, "подключение работает")
    except Exception as exc:
        return failed("База данных", exc)
    finally:
        await engine.dispose()


def config_checks(settings: Settings) -> list[CheckResult]:
    return [
        CheckResult(
            "Telegram",
            CheckStatus.OK if settings.telegram_bot_token else CheckStatus.SKIP,
            "токен задан" if settings.telegram_bot_token else "токен не задан",
        ),
        CheckResult(
            "OpenAI",
            CheckStatus.OK if settings.openai_api_key else CheckStatus.SKIP,
            (
                "ключ задан; live-запросы разрешены"
                if settings.openai_live_enabled
                else "ключ задан; расход токенов заблокирован"
            )
            if settings.openai_api_key
            else "ключ не задан",
        ),
        CheckResult(
            "Instagram API",
            CheckStatus.OK
            if settings.scrapecreators_api_key or settings.brightdata_api_key
            else CheckStatus.SKIP,
            (
                "ключи заданы; live-запросы разрешены"
                if settings.instagram_live_enabled
                else "ключи заданы; внешние запросы заблокированы"
            )
            if settings.scrapecreators_api_key or settings.brightdata_api_key
            else "ключи не заданы",
        ),
    ]


async def live_checks(settings: Settings) -> list[CheckResult]:
    """Run only after the user explicitly asks for --live.

    The checks are intentionally minimal: one Telegram getMe and at most one profile request per
    configured Instagram provider. OpenAI is not sent a completion; importing/configuring the
    client is enough here because model calls are the resource we want to protect.
    """
    results: list[CheckResult] = []
    if settings.telegram_bot_token:
        try:
            from aiogram import Bot

            bot = Bot(settings.telegram_bot_token)
            try:
                me = await bot.get_me()
                results.append(CheckResult("Telegram live", CheckStatus.OK, f"@{me.username or me.id}"))
            finally:
                await bot.session.close()
        except Exception as exc:
            results.append(failed("Telegram live", exc))

    results.extend(await instagram_live_checks(settings))
    return results


async def instagram_live_checks(settings: Settings) -> list[CheckResult]:
    """Explicit diagnostics use the same durable spend guards as manual scans."""
    names = [name for name, configured in (
        ("ScrapeCreators live", settings.scrapecreators_api_key),
        ("Bright Data live", settings.brightdata_api_key),
    ) if configured]
    if not names:
        return []
    if not settings.instagram_live_enabled:
        return [CheckResult(name, CheckStatus.SKIP,
            "Внешние запросы выключены настройками; запрос не отправлен") for name in names]
    if not settings.competitors:
        return [CheckResult(name, CheckStatus.SKIP,
            "Не задан публичный источник для проверки; запрос не отправлен") for name in names]

    from app.providers.brightdata import BrightDataProvider
    from app.providers.scrapecreators import ScrapeCreatorsProvider

    builders = {
        "ScrapeCreators live": lambda: ScrapeCreatorsProvider(
            settings.scrapecreators_api_key, base_url=settings.scrapecreators_api_url,
            timeout_seconds=settings.http_timeout_seconds, max_attempts=1, max_comment_pages=1,
        ),
        "Bright Data live": lambda: BrightDataProvider(
            settings.brightdata_api_key, api_url=settings.brightdata_api_url,
            profile_dataset_id=settings.brightdata_profile_dataset_id,
            posts_dataset_id=settings.brightdata_posts_dataset_id,
            reels_dataset_id=settings.brightdata_reels_dataset_id,
            comments_dataset_id=settings.brightdata_comments_dataset_id,
            timeout_seconds=settings.http_timeout_seconds, max_attempts=1,
        ),
    }
    engine = create_engine(settings)
    factory = create_session_factory(engine)
    usage = ExternalUsageService(factory)
    ops = OperationalControlService(factory)
    budget = ScanBudget(min(len(names), settings.instagram_max_units_per_scan))
    results: list[CheckResult] = []
    try:
        for name in names:
            provider = None
            try:
                provider = BudgetedInstagramProvider(
                    builders[name](), usage, enabled=settings.instagram_live_enabled,
                    daily_limit=settings.instagram_daily_request_limit, scan_budget=budget,
                    live_gate=ops.radar_live_armed, live_refresh=ops.radar_live_armed_fresh,
                )
                profile = await provider.get_profile(settings.competitors[0])
                results.append(CheckResult(name, CheckStatus.OK, f"получен @{profile.username}"))
            except ProviderUsageBlockedError as exc:
                results.append(CheckResult(name, CheckStatus.SKIP, str(exc)[:200]))
            except Exception as exc:
                results.append(failed(name, exc))
            finally:
                if provider is not None:
                    await provider.aclose()
    finally:
        await engine.dispose()
    return results


def failed(name: str, exc: Exception) -> CheckResult:
    return CheckResult(name, CheckStatus.FAIL, f"{type(exc).__name__}: {str(exc)[:140]}")


async def run_checks(*, live: bool) -> list[CheckResult]:
    settings = get_settings()
    results = [await check_database(settings), *config_checks(settings)]
    if live:
        results.extend(await live_checks(settings))
    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Lead Radar checks. By default it does not call external services."
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Explicitly allow minimal external connectivity checks (still respects live gates).",
    )
    args = parser.parse_args()
    print("Lead Radar V3 — проверка интеграций")
    print("Внешние запросы:", "РАЗРЕШЕНЫ ДЛЯ ПРОВЕРКИ" if args.live else "НЕ ВЫПОЛНЯЮТСЯ")
    print("=" * 64)
    results = asyncio.run(run_checks(live=args.live))
    for item in results:
        print(f"[{item.status.value:<4}] {item.name:<24} {item.details}")
    print("=" * 64)
    failures = sum(result.status == CheckStatus.FAIL for result in results)
    print(f"Ошибок: {failures}")
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
