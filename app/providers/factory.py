from app.config import Settings
from app.providers.base import InstagramProvider
from app.providers.brightdata import BrightDataProvider
from app.providers.fallback import FallbackInstagramProvider
from app.providers.mock import MockInstagramProvider
from app.providers.scrapecreators import ScrapeCreatorsProvider


def create_instagram_provider(settings: Settings) -> InstagramProvider:
    if settings.instagram_provider == "mock":
        return MockInstagramProvider()

    brightdata = BrightDataProvider(
        settings.brightdata_api_key,
        api_url=settings.brightdata_api_url,
        profile_dataset_id=settings.brightdata_profile_dataset_id,
        posts_dataset_id=settings.brightdata_posts_dataset_id,
        reels_dataset_id=settings.brightdata_reels_dataset_id,
        comments_dataset_id=settings.brightdata_comments_dataset_id,
        timeout_seconds=settings.http_timeout_seconds,
        max_attempts=settings.http_max_attempts,
    )
    if settings.instagram_provider == "brightdata":
        return brightdata

    scrapecreators = ScrapeCreatorsProvider(
        settings.scrapecreators_api_key,
        base_url=settings.scrapecreators_api_url,
        timeout_seconds=settings.http_timeout_seconds,
        max_attempts=settings.http_max_attempts,
    )
    return FallbackInstagramProvider(scrapecreators, brightdata)

