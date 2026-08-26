from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import StrEnum

from aiogram import Bot
from openai import AsyncOpenAI
from sqlalchemy import text

from app.config import Settings, get_settings
from app.db.session import create_engine
from app.providers.brightdata import BrightDataProvider
from app.providers.scrapecreators import ScrapeCreatorsProvider


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
        return CheckResult("Database", CheckStatus.OK, "connection and SELECT 1 succeeded")
    except Exception as exc:
        return failed("Database", exc)
    finally:
        await engine.dispose()


async def check_telegram(settings: Settings) -> CheckResult:
    if not settings.telegram_bot_token:
        return CheckResult("Telegram", CheckStatus.SKIP, "TELEGRAM_BOT_TOKEN is empty")
    bot = Bot(settings.telegram_bot_token)
    try:
        me = await bot.get_me()
        return CheckResult("Telegram", CheckStatus.OK, f"connected as @{me.username or me.id}")
    except Exception as exc:
        return failed("Telegram", exc)
    finally:
        await bot.session.close()


async def check_openai(settings: Settings) -> CheckResult:
    if not settings.openai_api_key:
        return CheckResult("OpenAI", CheckStatus.SKIP, "OPENAI_API_KEY is empty")
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    try:
        await client.models.list()
        return CheckResult(
            "OpenAI", CheckStatus.OK, f"API reachable; configured model={settings.openai_model}"
        )
    except Exception as exc:
        return failed("OpenAI", exc)
    finally:
        await client.close()


async def check_scrapecreators(settings: Settings) -> CheckResult:
    if not settings.scrapecreators_api_key:
        return CheckResult(
            "ScrapeCreators", CheckStatus.SKIP, "SCRAPECREATORS_API_KEY is empty"
        )
    provider = ScrapeCreatorsProvider(
        settings.scrapecreators_api_key,
        base_url=settings.scrapecreators_api_url,
        timeout_seconds=settings.http_timeout_seconds,
        max_attempts=1,
    )
    try:
        profile = await provider.get_profile(settings.competitors[0])
        return CheckResult(
            "ScrapeCreators", CheckStatus.OK, f"public profile @{profile.username} received"
        )
    except Exception as exc:
        return failed("ScrapeCreators", exc)
    finally:
        await provider.aclose()


async def check_brightdata(settings: Settings) -> CheckResult:
    if not settings.brightdata_api_key:
        return CheckResult("Bright Data", CheckStatus.SKIP, "BRIGHTDATA_API_KEY is empty")
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
        return CheckResult(
            "Bright Data", CheckStatus.OK, f"public profile @{profile.username} received"
        )
    except Exception as exc:
        return failed("Bright Data", exc)
    finally:
        await provider.aclose()


def failed(name: str, exc: Exception) -> CheckResult:
    status_code = getattr(exc, "status_code", None)
    suffix = f" (HTTP {status_code})" if status_code else ""
    return CheckResult(name, CheckStatus.FAIL, f"{type(exc).__name__}{suffix}")


async def run_checks() -> list[CheckResult]:
    settings = get_settings()
    return [
        await check_database(settings),
        await check_telegram(settings),
        await check_openai(settings),
        await check_scrapecreators(settings),
        await check_brightdata(settings),
    ]


def main() -> None:
    print("Lead Radar integration check")
    print("=" * 36)
    results = asyncio.run(run_checks())
    for item in results:
        print(f"[{item.status.value:<4}] {item.name:<15} {item.details}")
    print("=" * 36)
    failures = sum(result.status == CheckStatus.FAIL for result in results)
    skipped = sum(result.status == CheckStatus.SKIP for result in results)
    print(f"Result: {failures} failed, {skipped} skipped")
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()

