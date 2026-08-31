from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import (
    AIFeedback,
    Comment,
    Competitor,
    Contact,
    ContactEventType,
    ContactInterestProfile,
    Evidence,
    InterestEvidence,
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
    RuleBasedLeadAnalyzer,
    ValidatedPreviousSignal,
)
from app.services.contact_service import PersistedSignal

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from app.services.audience_service import AudienceEngine
    from app.services.significant_change_service import (
        IntelligenceSnapshot,
        SignificantChangeDetector,
    )

_STALE_ANALYZING_SECONDS = 15 * 60


@dataclass(frozen=True, slots=True)
class ProcessedLead:
    lead_id: int
    score: int
    status: LeadStatus
    created: bool
    is_hot: bool
    significant_change_id: int | None = None


class LeadService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        analyzer: LeadAnalyzer,
        hot_threshold: int,
        audience_engine: AudienceEngine | None = None,
        change_detector: SignificantChangeDetector | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.analyzer = analyzer
        self.hot_threshold = hot_threshold
        self.audience_engine = audience_engine
        self.change_detector = change_detector

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
            significant_change_id=analyzed.significant_change_id,
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
            public_signal = await session.scalar(
                select(PublicSignal).where(PublicSignal.comment_id == signal.comment_id)
            )
            lead = Lead(
                contact_id=signal.contact_id,
                comment_id=signal.comment_id,
                competitor_id=signal.competitor_id,
                vertical=(public_signal.vertical if public_signal else signal.vertical),
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
        contact_id: int | None = None
        change_before: IntelligenceSnapshot | None = None
        async with self.session_factory() as session:
            lead = await session.get(Lead, lead_id)
            if lead is None:
                raise RuntimeError(f"Lead {lead_id} was not found")
            context = await self._build_context(session, lead.comment_id)
            contact_id = lead.contact_id
            lead.ai_attempt_count += 1
            lead.ai_last_attempt_at = datetime.now(UTC)
            await session.commit()
        if self.change_detector is not None and contact_id is not None:
            try:
                change_before = await self.change_detector.snapshot(contact_id)
            except Exception as exc:
                logger.exception(
                    "significant_change_snapshot_failed contact_id=%s error_type=%s",
                    contact_id,
                    type(exc).__name__,
                )
        try:
            analysis, analysis_source = await self._analyze(context)
        except Exception as exc:
            async with self.session_factory() as session:
                lead = await session.get(Lead, lead_id)
                if lead is None:
                    raise RuntimeError(f"Lead {lead_id} was not found") from exc
                if lead.status == LeadStatus.ANALYZING:
                    lead.status = LeadStatus.AI_PENDING
                lead.ai_reason = (
                    "Нужна дополнительная проверка; сигнал сохранён и доступен менеджеру"
                )
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
            public_signal = await session.scalar(
                select(PublicSignal).where(PublicSignal.comment_id == lead.comment_id)
            )
            source_evidence = None
            if public_signal is not None:
                source_evidence = await session.scalar(
                    select(Evidence)
                    .where(Evidence.public_signal_id == public_signal.id)
                    .order_by(Evidence.id)
                )
            taxonomy = (
                ((source_evidence.raw_data or {}).get("rattan_taxonomy") or {})
                if source_evidence is not None
                else {}
            )
            taxonomy_products = list(taxonomy.get("products") or [])
            product_category = analysis.product_category
            if taxonomy.get("layer") == "RAW_MATERIAL" and taxonomy_products:
                product_category = str(taxonomy_products[0])
            previous_score = lead.lead_score
            lead.intent = analysis.intent.value
            lead.product_category = product_category
            lead.lead_score = analysis.lead_score
            lead.ai_reason = analysis.reason
            lead.analysis_details = analysis.model_dump(mode="json")
            lead.analysis_details["vertical"] = lead.vertical.value
            if taxonomy:
                lead.analysis_details["rattan_taxonomy"] = taxonomy
            lead.language = analysis.language
            lead.ai_source = analysis_source
            if lead.status in {LeadStatus.ANALYZING, LeadStatus.AI_PENDING}:
                lead.status = LeadStatus.NEW if analysis.is_lead else LeadStatus.NOT_LEAD
            contact.current_lead_score = max(contact.current_lead_score, analysis.lead_score)
            feedback = await session.scalar(select(AIFeedback).where(AIFeedback.lead_id == lead.id))
            if feedback is None:
                session.add(
                    AIFeedback(
                        contact_id=contact.id,
                        lead_id=lead.id,
                        comment_text=comment.text,
                        post_context=post.caption,
                        predicted_intent=analysis.intent.value,
                        predicted_product=product_category,
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
                    "product_category": product_category,
                    "confidence": analysis.confidence,
                    "funnel_stage": analysis.funnel_stage.value,
                    "urgency": analysis.urgency.value,
                    "buyer_role": analysis.buyer_role.value,
                    "intelligence_version": analysis.intelligence_version,
                    "factors": analysis.factors,
                    "evidence_ids": analysis.evidence_ids,
                },
            )
            if public_signal is not None:
                public_signal.status = PublicSignalStatus.ANALYZED
                public_signal.pipeline_stage = "COMPLETE"
                public_signal.error = None
                public_signal.analyzed_at = datetime.now(UTC)
            await session.commit()
            logger.info("lead_analysis_completed lead_id=%s score=%s", lead.id, lead.lead_score)
            contact_id = lead.contact_id
            result = self._to_result(lead, created=False)
        audience_recalculated = self.audience_engine is None
        if self.audience_engine is not None and contact_id is not None:
            try:
                await self.audience_engine.recalculate_contact(contact_id)
                audience_recalculated = True
            except Exception as exc:
                logger.exception(
                    "audience_recalculation_failed contact_id=%s error_type=%s",
                    contact_id,
                    type(exc).__name__,
                )
        if (
            self.change_detector is not None
            and contact_id is not None
            and change_before is not None
            and audience_recalculated
        ):
            try:
                change = await self.change_detector.detect_and_persist(
                    contact_id, lead_id, change_before
                )
                if change is not None:
                    result = replace(result, significant_change_id=change.id)
            except Exception as exc:
                logger.exception(
                    "significant_change_detection_failed contact_id=%s lead_id=%s error_type=%s",
                    contact_id,
                    lead_id,
                    type(exc).__name__,
                )
        return result

    async def backfill_unanalyzed_comments(self, limit: int = 25) -> list[ProcessedLead]:
        """Analyze stored signals that do not have a Lead yet, including baseline history.

        Historical comments are intentionally never notified here; this method only builds
        searchable lead intelligence in the database.
        """
        if limit <= 0:
            return []
        async with self.session_factory() as session:
            rows = (
                (
                    await session.execute(
                        select(Comment)
                        .outerjoin(Lead, Lead.comment_id == Comment.id)
                        .where(Lead.id.is_(None))
                        .order_by(Comment.created_at_platform.desc(), Comment.id.desc())
                        .limit(limit)
                    )
                )
                .scalars()
                .all()
            )

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
        stale_analyzing = datetime.now(UTC) - timedelta(seconds=max(cooldown_seconds, _STALE_ANALYZING_SECONDS))
        async with self.session_factory() as session:
            lead_ids = (
                await session.scalars(
                    select(Lead.id)
                    .where(
                        or_(
                            (
                                (Lead.status == LeadStatus.AI_PENDING)
                                & (
                                    Lead.ai_last_attempt_at.is_(None)
                                    | (Lead.ai_last_attempt_at <= cutoff)
                                )
                            ),
                            (
                                (Lead.status == LeadStatus.ANALYZING)
                                & (
                                    Lead.ai_last_attempt_at.is_(None)
                                    | (Lead.ai_last_attempt_at <= stale_analyzing)
                                )
                            ),
                        )
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

    async def retry_pending_lead(self, lead_id: int) -> ProcessedLead | None:
        """Повторный разбор одного AI_PENDING/ANALYZING лида тем же analyzer, что и batch retry."""
        return await self._retry_pending_one(lead_id)

    async def _retry_pending_one(self, lead_id: int) -> ProcessedLead | None:
        async with self.session_factory() as session:
            lead = await session.get(Lead, lead_id)
            if lead is None or lead.status not in {LeadStatus.AI_PENDING, LeadStatus.ANALYZING}:
                return None
        result = await self.analyze_lead(lead_id)
        return ProcessedLead(
            lead_id=result.lead_id,
            score=result.score,
            status=result.status,
            created=True,
            is_hot=result.is_hot,
            significant_change_id=result.significant_change_id,
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
            lead_ids = list(await session.scalars(select(Lead.id).order_by(Lead.id)))

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

    async def _build_context(self, session: AsyncSession, comment_id: int) -> LeadAnalysisContext:
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
        public_signal = await session.scalar(
            select(PublicSignal).where(PublicSignal.comment_id == comment.id)
        )
        history_rows = (
            await session.execute(
                select(Lead, PublicSignal, Competitor)
                .join(PublicSignal, PublicSignal.comment_id == Lead.comment_id)
                .join(Competitor, Competitor.id == Lead.competitor_id)
                .where(
                    Lead.contact_id == contact.id,
                    Lead.comment_id != comment.id,
                    Lead.vertical
                    == (public_signal.vertical if public_signal is not None else "FURNITURE"),
                )
                .order_by(Lead.created_at.desc())
                .limit(20)
            )
        ).all()
        history_signal_ids = [signal.id for _lead, signal, _competitor in history_rows]
        history_evidence = (
            list(
                await session.scalars(
                    select(Evidence).where(Evidence.public_signal_id.in_(history_signal_ids))
                )
            )
            if history_signal_ids
            else []
        )
        history_interest_evidence = (
            list(
                await session.scalars(
                    select(InterestEvidence).where(
                        InterestEvidence.contact_id == contact.id,
                        InterestEvidence.public_signal_id.in_(history_signal_ids),
                    )
                )
            )
            if history_signal_ids
            else []
        )
        evidence_by_signal: dict[int, set[int]] = {}
        for item in history_evidence:
            evidence_by_signal.setdefault(item.public_signal_id, set()).add(item.id)
        interests_by_signal: dict[int, list[InterestEvidence]] = {}
        for item in history_interest_evidence:
            interests_by_signal.setdefault(item.public_signal_id, []).append(item)

        previous: list[ValidatedPreviousSignal] = []
        for history_lead, history_signal, history_competitor in history_rows:
            details = history_lead.analysis_details or {}
            quality = str(details.get("commercial_quality") or "")
            buyer_role = str(details.get("buyer_role") or "UNKNOWN")
            intent = str(history_lead.intent or "")
            if (
                details.get("is_commercial") is not True
                or quality == "NON_COMMERCIAL"
                or buyer_role == "JOB_SEEKER"
                or intent in {"REACTION", "SPAM", "OTHER", ""}
            ):
                continue
            signal_interests = interests_by_signal.get(history_signal.id, [])
            validated_ids = sorted(
                evidence_by_signal.get(history_signal.id, set())
                & {item.evidence_id for item in signal_interests}
            )
            if not validated_ids:
                continue
            product_observations = [
                item for item in signal_interests if item.dimension == "PRODUCT"
            ]
            latest_observation = max(
                signal_interests,
                key=lambda item: item.observed_at,
            )
            latest_product = (
                max(product_observations, key=lambda item: item.observed_at).topic
                if product_observations
                else None
            )
            previous.append(
                ValidatedPreviousSignal(
                    lead_id=history_lead.id,
                    public_signal_id=history_signal.id,
                    evidence_ids=validated_ids,
                    competitor_id=history_competitor.id,
                    competitor=history_competitor.normalized_handle,
                    intent=intent,
                    product_family=latest_product,
                    buyer_role=buyer_role,
                    commercial_quality=quality,
                    priority_score=int(details.get("priority_score") or history_lead.lead_score),
                    confidence=int(
                        details.get("confidence_score") or details.get("confidence") or 0
                    ),
                    observed_at=latest_observation.observed_at.isoformat(),
                    vertical=history_lead.vertical.value,
                )
            )
        active_profiles = list(
            await session.scalars(
                select(ContactInterestProfile).where(
                    ContactInterestProfile.contact_id == contact.id,
                    ContactInterestProfile.vertical
                    == (public_signal.vertical.value if public_signal else "FURNITURE"),
                    ContactInterestProfile.dimension == "PRODUCT",
                    ContactInterestProfile.current_score >= 20,
                    ContactInterestProfile.confidence >= 50,
                )
            )
        )
        previous_interests = sorted(
            {
                profile.topic for profile in active_profiles
            }
            | {
                item.product_family
                for item in previous
                if item.product_family is not None
            }
        )
        lead_id = await session.scalar(select(Lead.id).where(Lead.comment_id == comment.id))
        evidence_ids: list[int] = []
        public_signal_id: int | None = None
        if public_signal is not None:
            public_signal_id = public_signal.id
            evidence_ids = list(
                await session.scalars(
                    select(Evidence.id)
                    .where(Evidence.public_signal_id == public_signal.id)
                    .order_by(Evidence.id)
                )
            )
        return LeadAnalysisContext(
            competitor=competitor.normalized_handle,
            post_caption=post.caption,
            comment=comment.text,
            username=contact.username,
            previous_signals=previous,
            previous_interests=previous_interests,
            known_customer_context={
                "city": contact.city,
                "interest_summary": contact.interest_summary,
                "desired_quantity": contact.desired_quantity,
                "budget_from": str(contact.budget_from)
                if contact.budget_from is not None
                else None,
                "budget_to": str(contact.budget_to) if contact.budget_to is not None else None,
                "desired_color": contact.desired_color,
                "purchase_timeline": contact.purchase_timeline,
                "qualification_note": contact.qualification_note,
            },
            evidence_ids=evidence_ids,
            public_signal_id=public_signal_id,
            lead_id=lead_id,
            stable_contact_id=(
                f"instagram:{contact.platform_user_id}"
                if contact.platform_user_id
                else f"contact:{contact.id}"
            ),
            vertical=(
                public_signal.vertical.value
                if public_signal is not None
                else "FURNITURE"
            ),
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
