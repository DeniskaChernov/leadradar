from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.config import Settings
from app.providers.base import InstagramProvider
from app.providers.brightdata import BrightDataProvider
from app.providers.budgeted import BudgetedInstagramProvider, ScanBudget
from app.providers.fallback import FallbackInstagramProvider
from app.providers.mock import MockInstagramProvider
from app.providers.replay import ReplayInstagramProvider
from app.providers.scrapecreators import ScrapeCreatorsProvider
from app.services.usage_service import ExternalUsageService


def create_instagram_provider(
    settings: Settings,
    usage: ExternalUsageService | None = None,
    *,
    live_gate: Callable[[], bool] | None = None,
    live_refresh: Callable[[], Awaitable[bool]] | None = None,
) -> InstagramProvider:
    if settings.instagram_provider == "mock":
        return MockInstagramProvider()
    if settings.instagram_provider == "replay":
        return ReplayInstagramProvider(settings.replay_fixture_path, settings.replay_state_path)

    scan_budget = ScanBudget(settings.instagram_max_units_per_scan)

    def guarded(provider: InstagramProvider) -> InstagramProvider:
        if usage is None:
            return provider
        return BudgetedInstagramProvider(
            provider,
            usage,
            enabled=settings.instagram_live_enabled,
            daily_limit=settings.instagram_daily_request_limit,
            scan_budget=scan_budget,
            live_gate=live_gate,
            live_refresh=live_refresh,
        )

    brightdata = guarded(
        BrightDataProvider(
            settings.brightdata_api_key,
            api_url=settings.brightdata_api_url,
            profile_dataset_id=settings.brightdata_profile_dataset_id,
            posts_dataset_id=settings.brightdata_posts_dataset_id,
            reels_dataset_id=settings.brightdata_reels_dataset_id,
            comments_dataset_id=settings.brightdata_comments_dataset_id,
            timeout_seconds=settings.http_timeout_seconds,
            max_attempts=settings.http_max_attempts,
        )
    )
    if settings.instagram_provider == "brightdata":
        return brightdata

    scrapecreators = guarded(
        ScrapeCreatorsProvider(
            settings.scrapecreators_api_key,
            base_url=settings.scrapecreators_api_url,
            timeout_seconds=settings.http_timeout_seconds,
            max_attempts=settings.http_max_attempts,
            max_comment_pages=settings.scrapecreators_max_comment_pages,
        )
    )
    return FallbackInstagramProvider(scrapecreators, brightdata)
