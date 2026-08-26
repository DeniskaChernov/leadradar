from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import text

from app.config import Settings, get_settings
from app.db.session import create_engine


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

    if settings.instagram_live_enabled and settings.scrapecreators_api_key:
        from app.providers.scrapecreators import ScrapeCreatorsProvider

        provider = ScrapeCreatorsProvider(
            settings.scrapecreators_api_key,
            base_url=settings.scrapecreators_api_url,
            timeout_seconds=settings.http_timeout_seconds,
            max_attempts=1,
            max_comment_pages=1,
        )
        try:
            profile = await provider.get_profile(settings.competitors[0])
            results.append(
                CheckResult("ScrapeCreators live", CheckStatus.OK, f"получен @{profile.username}")
            )
        except Exception as exc:
            results.append(failed("ScrapeCreators live", exc))
        finally:
            await provider.aclose()
    elif settings.scrapecreators_api_key:
        results.append(
            CheckResult(
                "ScrapeCreators live",
                CheckStatus.SKIP,
                "Live-запрос заблокирован двойным предохранителем — запрос не отправлен",
            )
        )

    if settings.instagram_live_enabled and settings.brightdata_api_key:
        from app.providers.brightdata import BrightDataProvider

        provider = BrightDataProvider(
            settings.brightdata_api_key,
            api_url=settings.brightdata_api_url,
            profile_dataset_id=settings.brightdata_profile_dataset_id,
            posts_dataset_id=settings.brightdata_posts_dataset_id,
            reels_dataset_id=settings.brightdata_reels_dataset_id,
            comments_dataset_id=settings.brightdata_comments_dataset_id,
            timeout_seconds=settings.http_timeout_seconds,
            max_attempts=1,
        )
        try:
            profile = await provider.get_profile(settings.competitors[0])
            results.append(CheckResult("Bright Data live", CheckStatus.OK, f"получен @{profile.username}"))
        except Exception as exc:
            results.append(failed("Bright Data live", exc))
        finally:
            await provider.aclose()
    elif settings.brightdata_api_key:
        results.append(
            CheckResult(
                "Bright Data live",
                CheckStatus.SKIP,
                "Live-запрос заблокирован двойным предохранителем — запрос не отправлен",
            )
        )
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
