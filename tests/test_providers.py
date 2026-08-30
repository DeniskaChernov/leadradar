import pytest

from app.providers.base import InstagramProvider, ProviderError
from app.providers.brightdata import BrightDataProvider
from app.providers.fallback import FallbackInstagramProvider
from app.providers.scrapecreators import ScrapeCreatorsProvider
from app.schemas.instagram import InstagramComment, InstagramPost, InstagramProfile


def test_scrapecreators_normalizes_documented_fields():
    post = ScrapeCreatorsProvider.normalize_post(
        {
            "id": "3600545900919030401_260462810",
            "code": "DH3tWudxIKB",
            "product_type": "clips",
            "caption": {"text": "Dining set"},
            "created_at": "2025-03-31T16:29:30.000Z",
            "comment_count": 12,
        },
        "aiko.uz",
    )
    comment = ScrapeCreatorsProvider.normalize_comment(
        {
            "id": "18051843701642870",
            "text": "narxi?",
            "created_at": "2025-09-16T17:03:04.000Z",
            "user": {"id": "46773599357", "username": "aziz_test"},
        }
    )

    assert post.platform_post_id == "3600545900919030401_260462810"
    assert post.comments_count == 12
    assert comment.platform_user_id == "46773599357"


def test_scrapecreators_captures_only_explicit_provider_credit_facts():
    provider = object.__new__(ScrapeCreatorsProvider)
    provider._credit_observations = []
    provider._capture_credit_observation(
        {
            "items": [],
            "credits_remaining": 21_842,
            "credits_charged": 1,
        },
        "https://api.scrapecreators.com/v2/instagram/user/posts",
    )
    observations = provider.pop_credit_observations()

    assert len(observations) == 1
    assert observations[0].operation == "get_reels"
    assert observations[0].credits_remaining == 21_842
    assert observations[0].credits_charged == 1
    assert provider.pop_credit_observations() == []


def test_brightdata_normalizes_documented_fields():
    post = BrightDataProvider.normalize_post(
        {
            "url": "https://www.instagram.com/reel/C5Rdyj_q7YN/",
            "shortcode": "C5Rdyj_q7YN",
            "description": "Watch this reel",
            "num_comments": 320,
            "date_posted": "2024-03-15T10:00:00.000Z",
        },
        "aiko.uz",
    )
    comment = BrightDataProvider.normalize_comment(
        {
            "comment_user": "user123",
            "comment_user_url": "https://www.instagram.com/user123",
            "comment_date": "2024-04-05T12:30:00.000Z",
            "comment": "Amazing post!",
            "comment_id": "18168596065410257",
            "post_id": "3851148751604100411",
        }
    )

    assert post.platform_post_id == "C5Rdyj_q7YN"
    assert post.comments_count == 320
    assert comment.username == "user123"


class StubProvider(InstagramProvider):
    def __init__(self, *, fail: bool) -> None:
        self.fail = fail
        self.calls = 0
        self.name = "failing" if fail else "working"

    async def get_profile(self, handle: str) -> InstagramProfile:
        self.calls += 1
        if self.fail:
            raise ProviderError("temporary")
        return InstagramProfile(username=handle, profile_url=f"https://instagram.com/{handle}")

    async def get_reels(self, handle: str) -> list[InstagramPost]:
        raise NotImplementedError

    async def get_post(self, url: str, competitor: str) -> InstagramPost:
        raise NotImplementedError

    async def get_comments(self, post: InstagramPost) -> list[InstagramComment]:
        raise NotImplementedError


@pytest.mark.asyncio
async def test_fallback_provider_activates_on_provider_error():
    primary = StubProvider(fail=True)
    fallback = StubProvider(fail=False)
    provider = FallbackInstagramProvider(primary, fallback)

    profile = await provider.get_profile("aiko.uz")

    assert profile.username == "aiko.uz"
    assert primary.calls == 1
    assert fallback.calls == 1
