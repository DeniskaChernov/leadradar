from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import (
    BusinessAlias,
    BusinessAliasType,
    BusinessEntity,
    BusinessEntityStatus,
    Comment,
    Competitor,
    ContactEventType,
    Evidence,
    PublicSignal,
    SignalSubjectType,
    SignalType,
    Vertical,
)
from app.db.repositories import (
    CommentRepository,
    CompetitorRepository,
    ContactEventRepository,
    ContactRepository,
    PostRepository,
)
from app.schemas.instagram import InstagramComment, InstagramPost
from app.services.rattan_taxonomy_service import RattanTaxonomyService

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
    vertical: Vertical = Vertical.FURNITURE


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
                    vertical=public_signal.vertical if public_signal else Vertical.FURNITURE,
                )

            try:
                taxonomy = RattanTaxonomyService.classify(
                    f"{post_data.caption}\n{comment_data.text}"
                )
                competitor = await CompetitorRepository(session).get_or_create(post_data.competitor)
                # Портфель ротанга только через explicit enrollment (Competitor.vertical в UI/CRM).
                # Таксономия размечает сигнал/evidence/lead, но не переводит источник.
                post, _, _ = await PostRepository(session).upsert(competitor, post_data)
                contact, contact_created = await ContactRepository(session).upsert_from_comment(
                    comment_data
                )
                business = await self._ensure_business(session, competitor)
                comment = Comment(
                    platform="instagram",
                    platform_comment_id=comment_data.platform_comment_id,
                    contact_id=contact.id,
                    post_id=post.id,
                    competitor_id=competitor.id,
                    text=comment_data.text,
                    created_at_platform=comment_data.created_at,
                    is_baseline=is_baseline,
                    parent_platform_comment_id=comment_data.parent_platform_comment_id,
                    parent_comment_text=await self._resolve_parent_comment_text(
                        session,
                        post_id=post.id,
                        parent_platform_comment_id=comment_data.parent_platform_comment_id,
                    ),
                    raw_data=comment_data.raw_data,
                )
                session.add(comment)
                await session.flush()
                public_signal = PublicSignal(
                    comment_id=comment.id,
                    contact_id=contact.id,
                    business_id=business.id,
                    competitor_id=competitor.id,
                    vertical=taxonomy.vertical,
                    subject_type=SignalSubjectType.CONTACT,
                    platform=comment.platform,
                    signal_type=SignalType.COMMENT,
                    external_id=comment.platform_comment_id,
                    dedupe_key=self._comment_dedupe_key(
                        comment.platform, comment.platform_comment_id
                    ),
                    source_url=post.url,
                    source_account=competitor.normalized_handle,
                    source_competitor_id=competitor.id,
                    text=comment.text,
                    payload_summary=comment.text[:500],
                    published_at=comment.created_at_platform,
                    discovered_at=comment.discovered_at,
                    source_quality_score=70,
                    confidence=100,
                    is_baseline=is_baseline,
                    raw_data=comment.raw_data,
                )
                session.add(public_signal)
                await session.flush()
                session.add(
                    Evidence(
                        evidence_key=f"{public_signal.dedupe_key}:source",
                        public_signal_id=public_signal.id,
                        vertical=taxonomy.vertical,
                        source_type="INSTAGRAM_COMMENT",
                        source_url=post.url,
                        text=comment.text,
                        confidence=100,
                        observed_at=comment.created_at_platform or comment.discovered_at,
                        topic=taxonomy.products[0] if taxonomy.products else None,
                        intent=(
                            taxonomy.layer.value
                            if taxonomy.is_rattan and taxonomy.layer.value != "NONE"
                            else None
                        ),
                        strength=taxonomy.confidence if taxonomy.is_rattan else 0,
                        raw_data={
                            **(comment.raw_data or {}),
                            "rattan_taxonomy": {
                                "version": RattanTaxonomyService.VERSION,
                                "layer": taxonomy.layer.value,
                                "role": taxonomy.role.value,
                                "products": list(taxonomy.products),
                                "material_profiles": list(taxonomy.material_profiles),
                                "evidence": list(taxonomy.evidence),
                                "negative_evidence": list(taxonomy.negative_evidence),
                            },
                        },
                    )
                )
                await ContactEventRepository(session).add(
                    contact.id,
                    ContactEventType.COMMENT_FOUND,
                    payload={
                        "platform_comment_id": comment_data.platform_comment_id,
                        "post_id": post.id,
                        "public_signal_id": public_signal.id,
                        "is_baseline": is_baseline,
                        "vertical": taxonomy.vertical.value,
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
                    vertical=taxonomy.vertical,
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
                    vertical=public_signal.vertical if public_signal else Vertical.FURNITURE,
                )

    @staticmethod
    async def _resolve_parent_comment_text(
        session: AsyncSession,
        *,
        post_id: int,
        parent_platform_comment_id: str | None,
    ) -> str | None:
        if not parent_platform_comment_id:
            return None
        parent_text = await session.scalar(
            select(Comment.text).where(
                Comment.post_id == post_id,
                Comment.platform_comment_id == parent_platform_comment_id,
            )
        )
        return (parent_text or "").strip() or None

    @staticmethod
    def _comment_dedupe_key(platform: str, external_id: str) -> str:
        return f"{platform.strip().lower()}:COMMENT:{external_id.strip()}"

    @staticmethod
    async def _ensure_business(
        session: AsyncSession, competitor: Competitor
    ) -> BusinessEntity:
        if competitor.business_id is not None:
            existing = await session.get(BusinessEntity, competitor.business_id)
            if existing is not None:
                existing.verticals_json = sorted(
                    set(existing.verticals_json or []).union({competitor.vertical.value})
                )
                return existing
        canonical_key = f"legacy-competitor:{competitor.id}"
        business = await session.scalar(
            select(BusinessEntity).where(BusinessEntity.canonical_key == canonical_key)
        )
        if business is None:
            name = competitor.display_name or competitor.normalized_handle
            business = BusinessEntity(
                canonical_key=canonical_key,
                canonical_name=name,
                normalized_name=name.strip().lower(),
                verticals_json=[competitor.vertical.value],
                website_url=competitor.website_url,
                instagram_handle=competitor.normalized_handle,
                primary_role=competitor.category,
                entity_status=BusinessEntityStatus.NEEDS_VERIFICATION,
                confidence=70,
            )
            session.add(business)
            await session.flush()
            session.add(
                BusinessAlias(
                    business_id=business.id,
                    alias_type=BusinessAliasType.INSTAGRAM_HANDLE,
                    value=competitor.normalized_handle,
                    normalized_value=competitor.normalized_handle,
                    source_url=(
                        f"https://www.instagram.com/{competitor.normalized_handle}/"
                    ),
                    confidence=100,
                    verified=True,
                )
            )
        competitor.business_id = business.id
        business.verticals_json = sorted(
            set(business.verticals_json or []).union({competitor.vertical.value})
        )
        await session.flush()
        return business
