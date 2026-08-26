from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

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
    PublicSignal,
    PublicSignalStatus,
)
from app.db.repositories.events import ContactEventRepository
from app.services.ai_service import (
    AIAnalysisError,
    LeadAnalysisContext,
    LeadAnalyzer,
    PreviousSignal,
    RuleBasedLeadAnalyzer,
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

    async def process_signal(
        self, signal: PersistedSignal, *, allow_baseline: bool = False
    ) -> ProcessedLead | None:
        if not signal.created or (signal.is_baseline and not allow_baseline):
            return None

        prepared = await self.ensure_analyzing(signal)
        if not prepared.created:
            return prepared
        analyzed = await self.analyze_lead(prepared.lead_id)
        return ProcessedLead(
            lead_id=analyzed.lead_id,
            score=analyzed.score,
            status=analyzed.status,
            created=True,
            is_hot=analyzed.is_hot,
        )

    async def ensure_analyzing(self, signal: PersistedSignal) -> ProcessedLead:
        """Create and commit the manager-visible lead shell before any analysis runs."""

        async with self.session_factory() as session:
            existing = await session.scalar(
                select(Lead).where(Lead.comment_id == signal.comment_id)
            )
            if existing is not None:
                return self._to_result(existing, created=False)
            comment = await session.get(Comment, signal.comment_id)
            contact = await session.get(Contact, signal.contact_id)
            if comment is None or contact is None:
                raise RuntimeError("Persisted signal references missing database rows")
            lead = Lead(
                contact_id=signal.contact_id,
                comment_id=signal.comment_id,
                competitor_id=signal.competitor_id,
                intent="OTHER",
                lead_score=0,
                ai_reason="Анализируем публичный коммерческий сигнал",
                ai_source="pending",
                status=LeadStatus.ANALYZING,
            )
            session.add(lead)
            try:
                await session.flush()
                await ContactEventRepository(session).add(
                    contact.id,
                    ContactEventType.LEAD_CREATED,
                    lead_id=lead.id,
                    payload={
                        "status": LeadStatus.ANALYZING.value,
                        "public_signal_id": signal.public_signal_id,
                    },
                )
                public_signal = await session.scalar(
                    select(PublicSignal).where(PublicSignal.comment_id == signal.comment_id)
                )
                if public_signal is not None:
                    public_signal.pipeline_stage = "LEAD_COMMITTED"
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
                "lead_analyzing_committed lead_id=%s contact_id=%s",
                lead.id,
                contact.id,
            )
            return self._to_result(lead, created=True)

    async def analyze_lead(self, lead_id: int) -> ProcessedLead:
        """Run enrichment after the initial lead and notification have been committed."""
        async with self.session_factory() as session:
            lead = await session.get(Lead, lead_id)
            if lead is None:
                raise RuntimeError(f"Lead {lead_id} was not found")
            context = await self._build_context(session, lead.comment_id)
            lead.ai_attempt_count += 1
            lead.ai_last_attempt_at = datetime.now(UTC)
            await session.commit()
        try:
            analysis, analysis_source = await self._analyze(context)
        except Exception as exc:
            async with self.session_factory() as session:
                lead = await session.get(Lead, lead_id)
                if lead is None:
                    raise RuntimeError(f"Lead {lead_id} was not found") from exc
                if lead.status == LeadStatus.ANALYZING:
                    lead.status = LeadStatus.AI_PENDING
                lead.ai_reason = "Нужна дополнительная проверка; сигнал сохранён и доступен менеджеру"
                public_signal = await session.scalar(
                    select(PublicSignal).where(PublicSignal.comment_id == lead.comment_id)
                )
                if public_signal is not None:
                    public_signal.status = PublicSignalStatus.FAILED
                    public_signal.pipeline_stage = "AI_PENDING"
                    public_signal.error = type(exc).__name__
                await session.commit()
                if isinstance(exc, AIAnalysisError):
                    logger.warning("lead_ai_pending lead_id=%s", lead_id)
                else:
                    logger.exception(
                        "lead_analysis_stage_failed lead_id=%s error_type=%s",
                        lead_id,
                        type(exc).__name__,
                    )
                return self._to_result(lead, created=False)

        async with self.session_factory() as session:
            lead = await session.get(Lead, lead_id)
            if lead is None:
                raise RuntimeError(f"Lead {lead_id} was not found")
            comment = await session.get(Comment, lead.comment_id)
            post = await session.get(Post, comment.post_id) if comment is not None else None
            contact = await session.get(Contact, lead.contact_id)
            if comment is None or post is None or contact is None:
                raise RuntimeError("Analyzing lead references missing database rows")
            previous_score = lead.lead_score
            lead.intent = analysis.intent.value
            lead.product_category = analysis.product_category
            lead.lead_score = analysis.lead_score
            lead.ai_reason = analysis.reason
            lead.analysis_details = analysis.model_dump(mode="json")
            lead.language = analysis.language
            lead.ai_source = analysis_source
            if lead.status in {LeadStatus.ANALYZING, LeadStatus.AI_PENDING}:
                lead.status = LeadStatus.NEW if analysis.is_lead else LeadStatus.NOT_LEAD
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
                ContactEventType.LEAD_SCORE_CHANGED,
                lead_id=lead.id,
                payload={
                    "from": previous_score,
                    "to": analysis.lead_score,
                    "intent": analysis.intent.value,
                    "product_category": analysis.product_category,
                    "confidence": analysis.confidence,
                    "funnel_stage": analysis.funnel_stage.value,
                    "urgency": analysis.urgency.value,
                },
            )
            public_signal = await session.scalar(
                select(PublicSignal).where(PublicSignal.comment_id == lead.comment_id)
            )
            if public_signal is not None:
                public_signal.status = PublicSignalStatus.ANALYZED
                public_signal.pipeline_stage = "COMPLETE"
                public_signal.error = None
                public_signal.analyzed_at = datetime.now(UTC)
            await session.commit()
            logger.info("lead_analysis_completed lead_id=%s score=%s", lead.id, lead.lead_score)
            return self._to_result(lead, created=False)

    async def backfill_unanalyzed_comments(self, limit: int = 25) -> list[ProcessedLead]:
        """Analyze stored signals that do not have a Lead yet, including baseline history.

        Historical comments are intentionally never notified here; this method only builds
        searchable lead intelligence in the database.
        """
        if limit <= 0:
            return []
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(Comment)
                    .outerjoin(Lead, Lead.comment_id == Comment.id)
                    .where(Lead.id.is_(None))
                    .order_by(Comment.created_at_platform.desc(), Comment.id.desc())
                    .limit(limit)
                )
            ).scalars().all()

        results: list[ProcessedLead] = []
        for comment in rows:
            signal = PersistedSignal(
                comment_id=comment.id,
                contact_id=comment.contact_id,
                post_id=comment.post_id,
                competitor_id=comment.competitor_id,
                created=True,
                is_baseline=comment.is_baseline,
            )
            result = await self.process_signal(signal, allow_baseline=True)
            if result is not None:
                results.append(result)
        return results

    async def retry_pending(
        self,
        limit: int = 50,
        *,
        cooldown_seconds: int = 0,
    ) -> list[ProcessedLead]:
        if limit <= 0:
            return []
        cutoff = datetime.now(UTC) - timedelta(seconds=cooldown_seconds)
        async with self.session_factory() as session:
            lead_ids = (
                await session.scalars(
                    select(Lead.id)
                    .where(
                        Lead.status == LeadStatus.AI_PENDING,
                        (Lead.ai_last_attempt_at.is_(None) | (Lead.ai_last_attempt_at <= cutoff)),
                    )
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
        result = await self.analyze_lead(lead_id)
        return ProcessedLead(
            lead_id=result.lead_id,
            score=result.score,
            status=result.status,
            created=True,
            is_hot=result.is_hot,
        )

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
                    ai_source="pending",
                    ai_attempt_count=1,
                    ai_last_attempt_at=datetime.now(UTC),
                    status=LeadStatus.AI_PENDING,
                )
                session.add(lead)
                try:
                    await session.commit()
                except IntegrityError:
                    await session.rollback()
                    lead = await session.scalar(
                        select(Lead).where(Lead.comment_id == signal.comment_id)
                    )
                    if lead is None:
                        raise
                    created = False
            return self._to_result(lead, created=created)

    async def backfill_analysis_details(self, *, limit: int = 500) -> int:
        """Enrich saved leads with the V3.5 explanation contract without external calls.

        The operation is idempotent and intentionally preserves the historical score, intent,
        status and reason. Only the new JSON explanation is filled for rows that do not have it.
        """
        async with self.session_factory() as session:
            lead_ids = list(
                await session.scalars(
                    select(Lead.id)
                    .order_by(Lead.id)
                )
            )

        rules = RuleBasedLeadAnalyzer()
        updated = 0
        for lead_id in lead_ids:
            if updated >= limit:
                break
            async with self.session_factory() as session:
                lead = await session.get(Lead, lead_id)
                if lead is None or lead.analysis_details is not None:
                    continue
                context = await self._build_context(session, lead.comment_id)
            analysis = await rules.analyze(context)
            details = analysis.model_dump(mode="json")
            details.update(
                {
                    "is_lead": lead.status
                    not in {LeadStatus.NOT_LEAD, LeadStatus.AI_PENDING, LeadStatus.ANALYZING},
                    "lead_score": lead.lead_score,
                    "intent": lead.intent,
                    "product_category": lead.product_category,
                    "language": lead.language or analysis.language,
                    "reason": lead.ai_reason or analysis.reason,
                }
            )
            async with self.session_factory() as session:
                current = await session.get(Lead, lead_id)
                if current is None or current.analysis_details is not None:
                    continue
                current.analysis_details = details
                await session.commit()
                updated += 1
        return updated

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
            known_customer_context={
                "city": contact.city,
                "interest_summary": contact.interest_summary,
                "desired_quantity": contact.desired_quantity,
                "budget_from": str(contact.budget_from) if contact.budget_from is not None else None,
                "budget_to": str(contact.budget_to) if contact.budget_to is not None else None,
                "desired_color": contact.desired_color,
                "purchase_timeline": contact.purchase_timeline,
                "qualification_note": contact.qualification_note,
            },
        )


    async def _analyze(self, context: LeadAnalysisContext):
        analyze_with_source = getattr(self.analyzer, "analyze_with_source", None)
        if analyze_with_source is not None:
            return await analyze_with_source(context)
        return await self.analyzer.analyze(context), "custom_analyzer"

    def _to_result(self, lead: Lead, *, created: bool) -> ProcessedLead:
        return ProcessedLead(
            lead_id=lead.id,
            score=lead.lead_score,
            status=lead.status,
            created=created,
            is_hot=(
                lead.lead_score >= self.hot_threshold
                and lead.status not in {LeadStatus.NOT_LEAD, LeadStatus.LOST}
            ),
        )
