from datetime import UTC, datetime

from sqlalchemy import select
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

    async def upsert(
        self, competitor: Competitor, post_data: InstagramPost, platform: str = "instagram"
    ) -> tuple[Post, bool, int | None]:
        post = await self.get_by_platform_id(post_data.platform_post_id, platform)
        previous_comments_count = post.comments_count if post else None
        created = post is None
        if post is None:
            post = Post(
                platform=platform,
                platform_post_id=post_data.platform_post_id,
                competitor_id=competitor.id,
                url=post_data.url,
                caption=post_data.caption,
                post_type=post_data.post_type,
                published_at=post_data.published_at,
                comments_count=post_data.comments_count,
                raw_data=post_data.raw_data,
            )
            self.session.add(post)
        else:
            post.url = post_data.url
            post.caption = post_data.caption
            post.post_type = post_data.post_type
            post.published_at = post_data.published_at or post.published_at
            post.comments_count = post_data.comments_count
            post.last_checked_at = datetime.now(UTC)
            post.raw_data = post_data.raw_data
        await self.session.flush()
        return post, created, previous_comments_count

