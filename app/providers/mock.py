from __future__ import annotations

from datetime import UTC, datetime

from app.providers.base import InstagramProvider, ProviderResponseError
from app.schemas.instagram import (
    CommentFetchResult,
    InstagramComment,
    InstagramPost,
    InstagramProfile,
)


class MockInstagramProvider(InstagramProvider):
    name = "mock"

    def __init__(self) -> None:
        self._post = InstagramPost(
            platform_post_id="mock-reel-001",
            competitor="aiko.uz",
            url="https://www.instagram.com/reel/mock-reel-001/",
            caption=(
                "Обеденный комплект на 6 персон. "
                "Для получения цены напишите + в комментариях."
            ),
            post_type="REEL",
            published_at=datetime(2026, 8, 26, 8, 0, tzinfo=UTC),
            comments_count=1,
            raw_data={"source": "mock"},
        )
        self._comments = [
            InstagramComment(
                platform_comment_id="mock-comment-001",
                platform_user_id="mock-user-aziz-001",
                username="aziz_test",
                display_name="Aziz",
                profile_url="https://www.instagram.com/aziz_test/",
                text="+",
                created_at=datetime(2026, 8, 26, 8, 1, tzinfo=UTC),
                raw_data={"source": "mock"},
            )
        ]

    async def get_profile(self, handle: str) -> InstagramProfile:
        normalized = handle.strip().lower().lstrip("@")
        return InstagramProfile(
            platform_user_id=f"mock-profile-{normalized}",
            username=normalized,
            display_name=normalized.upper(),
            profile_url=f"https://www.instagram.com/{normalized}/",
            raw_data={"source": "mock"},
        )

    async def get_reels(self, handle: str) -> list[InstagramPost]:
        normalized = handle.strip().lower().lstrip("@")
        return [self._post.model_copy(update={"competitor": normalized})]

    async def get_post(self, url: str, competitor: str) -> InstagramPost:
        if url != self._post.url:
            raise ProviderResponseError(f"Unknown mock post URL: {url}")
        return self._post.model_copy(update={"competitor": competitor})

    async def get_comments(self, post: InstagramPost) -> list[InstagramComment]:
        return (await self.get_comment_batch(post)).comments

    async def get_comment_batch(
        self,
        post: InstagramPost,
        *,
        known_comment_ids: set[str] | None = None,
        max_pages: int | None = None,
    ) -> CommentFetchResult:
        if post.platform_post_id != self._post.platform_post_id:
            raise ProviderResponseError(f"Unknown mock post: {post.platform_post_id}")
        return CommentFetchResult(
            comments=list(self._comments),
            provider=self.name,
            pages_fetched=1,
            coverage_status="FULL",
            cursor_exhausted=True,
        )

    def add_comment(self, comment: InstagramComment) -> None:
        self._comments.append(comment)
        self._post = self._post.model_copy(update={"comments_count": len(self._comments)})

