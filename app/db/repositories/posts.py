from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Competitor, Post
from app.schemas.instagram import InstagramPost


class PostRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_platform_id(
        self, platform_post_id: str, platform: str = "instagram"
    ) -> Post | None:
        return await self.session.scalar(
            select(Post).where(
                Post.platform == platform,
                Post.platform_post_id == platform_post_id,
            )
        )

    async def get_by_identity(
        self, platform_post_id: str, url: str, platform: str = "instagram"
    ) -> Post | None:
        normalized_url = normalize_post_url(url)
        return await self.session.scalar(
            select(Post).where(
                Post.platform == platform,
                or_(
                    Post.platform_post_id == platform_post_id,
                    Post.url == normalized_url,
                ),
            )
        )

    async def upsert(
        self, competitor: Competitor, post_data: InstagramPost, platform: str = "instagram"
    ) -> tuple[Post, bool, int | None]:
        normalized_url = normalize_post_url(post_data.url)
        post = await self.get_by_identity(
            post_data.platform_post_id, normalized_url, platform
        )
        previous_comments_count = post.comments_count if post else None
        created = post is None
        if post is None:
            post = Post(
                platform=platform,
                platform_post_id=post_data.platform_post_id,
                competitor_id=competitor.id,
                url=normalized_url,
                caption=post_data.caption,
                post_type=post_data.post_type,
                published_at=post_data.published_at,
                comments_count=post_data.comments_count,
                raw_data=post_data.raw_data,
            )
            self.session.add(post)
        else:
            post.url = normalized_url
            post.caption = post_data.caption
            post.post_type = post_data.post_type
            post.published_at = post_data.published_at or post.published_at
            post.comments_count = post_data.comments_count
            post.last_checked_at = datetime.now(UTC)
            post.raw_data = post_data.raw_data
        await self.session.flush()
        return post, created, previous_comments_count


def normalize_post_url(url: str) -> str:
    return url.split("?", maxsplit=1)[0].rstrip("/") + "/"
