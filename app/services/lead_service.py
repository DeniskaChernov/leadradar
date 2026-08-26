from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.db.models import (
    AIFeedback,
    Comment,
    Competitor,
    Contact,
    ContactEventType,
    Lead,
    LeadStatus,
    Post,
)
from app.db.repositories.events import ContactEventRepository
from app.services.ai_service import (
    AIAnalysisError,
    LeadAnalysisContext,
    LeadAnalyzer,
    PreviousSignal,
)
from app.services.contact_service import PersistedSignal

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ProcessedLead:
    lead_id: int
    score: int
    status: LeadStatus
    created: bool
    is_hot: bool


class LeadService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        analyzer: LeadAnalyzer,
        hot_threshold: int,
    ) -> None:
        self.session_factory = session_factory
        self.analyzer = analyzer
        self.hot_threshold = hot_threshold

    async def process_signal(self, signal: PersistedSignal) -> ProcessedLead | None:
        if not signal.created or signal.is_baseline:
            return None

        async with self.session_factory() as session:
            existing = await session.scalar(
                select(Lead).where(Lead.comment_id == signal.comment_id)
            )
            if existing is not None:
                return self._to_result(existing, created=False)
            context = await self._build_context(session, signal.comment_id)

        try:
            analysis = await self.analyzer.analyze(context)
        except AIAnalysisError:
            logger.warning("lead_ai_pending comment_id=%s", signal.comment_id)
            return await self._create_pending(signal)

        async with self.session_factory() as session:
            existing = await session.scalar(
                select(Lead).where(Lead.comment_id == signal.comment_id)
            )
            if existing is not None:
                return self._to_result(existing, created=False)
            comment = await session.get(Comment, signal.comment_id)
            post = await session.get(Post, signal.post_id)
            contact = await session.get(Contact, signal.contact_id)
            if comment is None or post is None or contact is None:
                raise RuntimeError("Persisted signal references missing database rows")
            lead = Lead(
                contact_id=signal.contact_id,
                comment_id=signal.comment_id,
                competitor_id=signal.competitor_id,
                intent=analysis.intent.value,
                product_category=analysis.product_category,
                lead_score=analysis.lead_score,
                ai_reason=analysis.reason,
                language=analysis.language,
                status=LeadStatus.NEW,
            )
            session.add(lead)
            try:
                await session.flush()
                contact.current_lead_score = max(
                    contact.current_lead_score, analysis.lead_score
                )
                await ContactEventRepository(session).add(
                    contact.id,
                    ContactEventType.LEAD_CREATED,
                    lead_id=lead.id,
                    payload={
                        "score": analysis.lead_score,
                        "intent": analysis.intent.value,
                        "product_category": analysis.product_category,
                    },
                )
                session.add(
                    AIFeedback(
                        contact_id=contact.id,
                        lead_id=lead.id,
                        comment_text=comment.text,
                        post_context=post.caption,
                        predicted_intent=analysis.intent.value,
                        predicted_product=analysis.product_category,
                        predicted_score=analysis.lead_score,
                    )
                )
                await session.commit()
            except IntegrityError:
                await session.rollback()
                existing = await session.scalar(
                    select(Lead).where(Lead.comment_id == signal.comment_id)
                )
                if existing is None:
                    raise
                return self._to_result(existing, created=False)
            logger.info(
                "lead_created lead_id=%s contact_id=%s score=%s",
                lead.id,
                contact.id,
                lead.lead_score,
            )
            return self._to_result(lead, created=True)

    async def retry_pending(self, limit: int = 50) -> list[ProcessedLead]:
        async with self.session_factory() as session:
            lead_ids = (
                await session.scalars(
                    select(Lead.id)
                    .where(Lead.status == LeadStatus.AI_PENDING)
                    .order_by(Lead.created_at)
                    .limit(limit)
                )
            ).all()
        results: list[ProcessedLead] = []
        for lead_id in lead_ids:
            result = await self._retry_pending_one(lead_id)
            if result is not None:
                results.append(result)
        return results

    async def _retry_pending_one(self, lead_id: int) -> ProcessedLead | None:
        async with self.session_factory() as session:
            lead = await session.get(Lead, lead_id)
            if lead is None or lead.status != LeadStatus.AI_PENDING:
                return None
            context = await self._build_context(session, lead.comment_id)
        try:
            analysis = await self.analyzer.analyze(context)
        except AIAnalysisError:
            return None

        async with self.session_factory() as session:
            lead = await session.get(Lead, lead_id)
            if lead is None or lead.status != LeadStatus.AI_PENDING:
                return None
            comment = await session.get(Comment, lead.comment_id)
            post = await session.get(Post, comment.post_id) if comment is not None else None
            contact = await session.get(Contact, lead.contact_id)
            if comment is None or post is None or contact is None:
                raise RuntimeError("Pending lead references missing database rows")
            lead.intent = analysis.intent.value
            lead.product_category = analysis.product_category
            lead.lead_score = analysis.lead_score
            lead.ai_reason = analysis.reason
            lead.language = analysis.language
            lead.status = LeadStatus.NEW
            contact.current_lead_score = max(contact.current_lead_score, analysis.lead_score)
            feedback = await session.scalar(
                select(AIFeedback).where(AIFeedback.lead_id == lead.id)
            )
            if feedback is None:
                session.add(
                    AIFeedback(
                        contact_id=contact.id,
                        lead_id=lead.id,
                        comment_text=comment.text,
                        post_context=post.caption,
                        predicted_intent=analysis.intent.value,
                        predicted_product=analysis.product_category,
                        predicted_score=analysis.lead_score,
                    )
                )
                await ContactEventRepository(session).add(
                    contact.id,
                    ContactEventType.LEAD_CREATED,
                    lead_id=lead.id,
                    payload={
                        "score": analysis.lead_score,
                        "intent": analysis.intent.value,
                        "product_category": analysis.product_category,
                        "from_ai_pending": True,
                    },
                )
            await session.commit()
            logger.info("pending_lead_processed lead_id=%s score=%s", lead.id, lead.lead_score)
            return self._to_result(lead, created=True)

    async def _create_pending(self, signal: PersistedSignal) -> ProcessedLead:
        async with self.session_factory() as session:
            lead = await session.scalar(select(Lead).where(Lead.comment_id == signal.comment_id))
            created = lead is None
            if lead is None:
                lead = Lead(
                    contact_id=signal.contact_id,
                    comment_id=signal.comment_id,
                    competitor_id=signal.competitor_id,
                    intent="OTHER",
                    lead_score=0,
                    ai_reason="AI analysis pending retry",
                    status=LeadStatus.AI_PENDING,
                )
                session.add(lead)
                await session.commit()
            return self._to_result(lead, created=created)

    async def _build_context(
        self, session: AsyncSession, comment_id: int
    ) -> LeadAnalysisContext:
        row = (
            await session.execute(
                select(Comment, Contact, Post, Competitor)
                .join(Contact, Comment.contact_id == Contact.id)
                .join(Post, Comment.post_id == Post.id)
                .join(Competitor, Comment.competitor_id == Competitor.id)
                .where(Comment.id == comment_id)
            )
        ).one_or_none()
        if row is None:
            raise RuntimeError(f"Comment {comment_id} was not found")
        comment, contact, post, competitor = row
        history_rows = (
            await session.execute(
                select(Comment, Post, Competitor)
                .join(Post, Comment.post_id == Post.id)
                .join(Competitor, Comment.competitor_id == Competitor.id)
                .where(Comment.contact_id == contact.id, Comment.id != comment.id)
                .order_by(Comment.discovered_at.desc())
                .limit(20)
            )
        ).all()
        previous = [
            PreviousSignal(
                competitor=history_competitor.normalized_handle,
                post_caption=history_post.caption,
                comment=history_comment.text,
                discovered_at=history_comment.discovered_at.isoformat(),
            )
            for history_comment, history_post, history_competitor in history_rows
        ]
        interests = (
            await session.scalars(
                select(Lead)
                .options(selectinload(Lead.comment))
                .where(Lead.contact_id == contact.id, Lead.product_category.is_not(None))
                .order_by(Lead.created_at.desc())
                .limit(10)
            )
        ).all()
        return LeadAnalysisContext(
            competitor=competitor.normalized_handle,
            post_caption=post.caption,
            comment=comment.text,
            username=contact.username,
            previous_signals=previous,
            previous_interests=[
                lead.product_category for lead in interests if lead.product_category
            ],
        )

    def _to_result(self, lead: Lead, *, created: bool) -> ProcessedLead:
        return ProcessedLead(
            lead_id=lead.id,
            score=lead.lead_score,
            status=lead.status,
            created=created,
            is_hot=lead.lead_score >= self.hot_threshold,
        )
