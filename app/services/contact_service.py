from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Comment, ContactEventType, PublicSignal
from app.db.repositories import (
    CommentRepository,
    CompetitorRepository,
    ContactEventRepository,
    ContactRepository,
    PostRepository,
)
from app.schemas.instagram import InstagramComment, InstagramPost

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PersistedSignal:
    comment_id: int
    contact_id: int
    post_id: int
    competitor_id: int
    created: bool
    is_baseline: bool
    public_signal_id: int | None = None


class ContactService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def persist_signal(
        self,
        post_data: InstagramPost,
        comment_data: InstagramComment,
        *,
        is_baseline: bool = False,
    ) -> PersistedSignal:
        for attempt in range(2):
            result = await self._persist_signal_once(
                post_data, comment_data, is_baseline=is_baseline
            )
            if result is not None:
                return result
            logger.info(
                "signal_persist_retry platform_comment_id=%s attempt=%s",
                comment_data.platform_comment_id,
                attempt + 2,
            )
        raise RuntimeError("Signal persistence retry was exhausted")

    async def _persist_signal_once(
        self,
        post_data: InstagramPost,
        comment_data: InstagramComment,
        *,
        is_baseline: bool,
    ) -> PersistedSignal | None:
        async with self.session_factory() as session:
            comments = CommentRepository(session)
            existing = await comments.get_by_platform_id(comment_data.platform_comment_id)
            if existing is not None:
                public_signal = await session.scalar(
                    select(PublicSignal).where(PublicSignal.comment_id == existing.id)
                )
                return PersistedSignal(
                    comment_id=existing.id,
                    contact_id=existing.contact_id,
                    post_id=existing.post_id,
                    competitor_id=existing.competitor_id,
                    created=False,
                    is_baseline=existing.is_baseline,
                    public_signal_id=public_signal.id if public_signal else None,
                )

            try:
                competitor = await CompetitorRepository(session).get_or_create(post_data.competitor)
                post, _, _ = await PostRepository(session).upsert(competitor, post_data)
                contact, contact_created = await ContactRepository(session).upsert_from_comment(
                    comment_data
                )
                comment = Comment(
                    platform="instagram",
                    platform_comment_id=comment_data.platform_comment_id,
                    contact_id=contact.id,
                    post_id=post.id,
                    competitor_id=competitor.id,
                    text=comment_data.text,
                    created_at_platform=comment_data.created_at,
                    is_baseline=is_baseline,
                    raw_data=comment_data.raw_data,
                )
                session.add(comment)
                await session.flush()
                public_signal = PublicSignal(
                    comment_id=comment.id,
                    contact_id=contact.id,
                    competitor_id=competitor.id,
                )
                session.add(public_signal)
                await session.flush()
                await ContactEventRepository(session).add(
                    contact.id,
                    ContactEventType.COMMENT_FOUND,
                    payload={
                        "platform_comment_id": comment_data.platform_comment_id,
                        "post_id": post.id,
                        "public_signal_id": public_signal.id,
                        "is_baseline": is_baseline,
                    },
                )
                await session.commit()
                logger.info(
                    "signal_persisted comment_id=%s contact_id=%s contact_created=%s baseline=%s",
                    comment.id,
                    contact.id,
                    contact_created,
                    is_baseline,
                )
                return PersistedSignal(
                    comment_id=comment.id,
                    contact_id=contact.id,
                    post_id=post.id,
                    competitor_id=competitor.id,
                    created=True,
                    is_baseline=is_baseline,
                    public_signal_id=public_signal.id,
                )
            except IntegrityError:
                await session.rollback()
                existing = await CommentRepository(session).get_by_platform_id(
                    comment_data.platform_comment_id
                )
                if existing is None:
                    return None
                public_signal = await session.scalar(
                    select(PublicSignal).where(PublicSignal.comment_id == existing.id)
                )
                return PersistedSignal(
                    comment_id=existing.id,
                    contact_id=existing.contact_id,
                    post_id=existing.post_id,
                    competitor_id=existing.competitor_id,
                    created=False,
                    is_baseline=existing.is_baseline,
                    public_signal_id=public_signal.id if public_signal else None,
                )
