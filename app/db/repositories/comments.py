from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Comment


class CommentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_platform_id(
        self, platform_comment_id: str, platform: str = "instagram"
    ) -> Comment | None:
        return await self.session.scalar(
            select(Comment).where(
                Comment.platform == platform,
                Comment.platform_comment_id == platform_comment_id,
            )
        )

    async def count_for_contact(self, contact_id: int) -> int:
        rows = await self.session.scalars(
            select(Comment.id).where(Comment.contact_id == contact_id)
        )
        return len(rows.all())

