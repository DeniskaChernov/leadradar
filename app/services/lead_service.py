from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import (
    AIFeedback,
    AIRequest,
    AIRequestStatus,
    Comment,
    Competitor,
    Contact,
    ContactEvent,
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
from app.schemas.leads import Intent, LeadAnalysis
from app.services.ai_service import (
    AIAnalysisError,
    LeadAnalysisContext,
    LeadAnalyzer,
    RuleBasedLeadAnalyzer,
    ValidatedPreviousSignal,
)
from app.services.assortment_policy import apply_assortment, assess_assortment, assortment_eligible
from app.services.contact_service import PersistedSignal
from app.services.place_opening_service import PlaceOpeningService
from app.services.product_context_service import resolve_product_context
from app.services.signal_recency import (
    fresh_signal_clause,
    is_signal_within_window,
    signal_observed_at,
)
from app.services.usage_service import ExternalBudgetExceeded

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
        *,
        signal_max_age_days: int = 30,
        rules_version: str = "3.3",
    ) -> None:
        self.session_factory = session_factory
        self.analyzer = analyzer
        self.hot_threshold = hot_threshold
        self.audience_engine = audience_engine
        self.change_detector = change_detector
        self.signal_max_age_days = max(0, signal_max_age_days)
        self.rules_version = (rules_version or "3.3").strip() or "3.3"

    async def process_signal(
        self, signal: PersistedSignal, *, allow_baseline: bool = False
    ) -> ProcessedLead | None:
        if not signal.created or (signal.is_baseline and not allow_baseline):
            return None
        if not await self._signal_is_fresh(signal.comment_id):
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
                await PlaceOpeningService.capture_lead(
                    session, lead, comment, max_age_days=self.signal_max_age_days
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
                "lead_analyzing_committed lead_id=%s contact_id=%s",
                lead.id,
                contact.id,
            )
            return self._to_result(lead, created=True)

    async def analyze_lead(self, lead_id: int, *, local_only: bool = False,
                           pending_only: bool = False) -> ProcessedLead:
        """Run enrichment after the initial lead and notification have been committed."""
        contact_id: int | None = None
        change_before: IntelligenceSnapshot | None = None
        async with self.session_factory() as session:
            lead = await session.get(Lead, lead_id)
            if lead is None:
                raise RuntimeError(f"Lead {lead_id} was not found")
            if pending_only and lead.status not in {LeadStatus.AI_PENDING, LeadStatus.ANALYZING}:
                return self._to_result(lead, created=False)
            if local_only and pending_only and await self._has_claimed_ai_request(session, lead.id):
                return self._to_result(lead, created=False)
            context = await self._build_context(session, lead.comment_id)
            assortment = assess_assortment(context.comment, context.post_caption, context.parent_comment,
                                          vertical=context.vertical)
            local_analysis = (
                RuleBasedLeadAnalyzer().classify(context)
                if local_only or RuleBasedLeadAnalyzer.is_price_acknowledgement(context.comment) or assortment.status == "EXCLUDED"
                else None
            )
            if local_only and local_analysis is None:
                return self._to_result(lead, created=False)
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
            if local_analysis is not None:
                analysis, analysis_source = local_analysis, "local_rules"
            else:
                analysis, analysis_source = await self._analyze(context)
            analysis = apply_assortment(analysis, assortment)
        except Exception as exc:
            async with self.session_factory() as session:
                await session.execute(
                    update(Lead).where(Lead.id == lead_id).values(updated_at=Lead.updated_at)
                )
                lead = await session.get(Lead, lead_id)
                if lead is None:
                    raise RuntimeError(f"Lead {lead_id} was not found") from exc
                if lead.status == LeadStatus.ANALYZING:
                    lead.status = LeadStatus.AI_PENDING
                lead.ai_reason = (
                    "Оценка отложена: достигнут лимит AI. Сигнал сохранён и доступен менеджеру."
                    if isinstance(exc, ExternalBudgetExceeded)
                    else "Нужна дополнительная проверка; сигнал сохранён и доступен менеджеру"
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
            # Lock the short final write before reading shared workflow metadata.
            # No provider or analyzer call runs while this transaction holds the lock.
            await session.execute(
                update(Lead).where(Lead.id == lead_id).values(updated_at=Lead.updated_at)
            )
            lead = await session.get(Lead, lead_id)
            if lead is None:
                raise RuntimeError(f"Lead {lead_id} was not found")
            if pending_only and lead.status not in {LeadStatus.AI_PENDING, LeadStatus.ANALYZING}:
                return self._to_result(lead, created=False)
            if local_only and pending_only and await self._has_claimed_ai_request(session, lead.id):
                return self._to_result(lead, created=False)
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
            feedback = await session.scalar(select(AIFeedback).where(AIFeedback.lead_id == lead.id))
            manually_rejected = False
            if lead.status == LeadStatus.NOT_LEAD:
                # A decision can be committed before the first AI feedback exists.
                last_decision = await session.scalar(
                    select(ContactEvent.event_type)
                    .where(
                        ContactEvent.lead_id == lead.id,
                        ContactEvent.event_type.in_(
                            [ContactEventType.MANAGER_MARKED_NOT_LEAD, ContactEventType.LEAD_REOPENED]
                        ),
                    )
                    .order_by(ContactEvent.id.desc())
                    .limit(1)
                )
                manually_rejected = (
                    last_decision == ContactEventType.MANAGER_MARKED_NOT_LEAD
                    or (
                        feedback is not None
                        and feedback.manager_is_lead is False
                        and feedback.actual_outcome == LeadStatus.NOT_LEAD.value
                    )
                )
            product_category = analysis.product_category
            product_context = resolve_product_context(
                context.comment, context.post_caption, context.parent_comment,
            )
            if product_context.categories and (
                product_context.source != "POST_CAPTION"
                or product_context.category is None
                or analysis_source == "local_rules"
            ):
                product_category = product_context.category
            if taxonomy.get("layer") == "RAW_MATERIAL" and taxonomy_products:
                product_category = str(taxonomy_products[0])
            previous_score = lead.lead_score
            lead.intent = analysis.intent.value
            lead.product_category = product_category
            lead.lead_score = analysis.lead_score
            lead.ai_reason = analysis.reason
            outreach = (lead.analysis_details or {}).get("hot_outreach")
            lead.analysis_details = analysis.model_dump(mode="json")
            lead.analysis_details["product_category"] = product_category
            if (
                product_context.categories and product_category == product_context.category
                and taxonomy.get("layer") != "RAW_MATERIAL"
            ):
                lead.analysis_details["product_context"] = product_context.as_dict()
            if product_category == "MIXED_FURNITURE":
                lead.analysis_details["quantity"] = None
            if outreach is not None:
                lead.analysis_details["hot_outreach"] = outreach
            lead.analysis_details["vertical"] = lead.vertical.value
            lead.analysis_details["rules_version"] = self.rules_version
            lead.analysis_details["assortment"] = assortment.as_dict()
            if RuleBasedLeadAnalyzer.is_price_acknowledgement(context.comment):
                lead.analysis_details["qualification_guard"] = "price_acknowledgement:v1"
            if taxonomy:
                lead.analysis_details["rattan_taxonomy"] = taxonomy
            lead.language = analysis.language
            lead.ai_source = analysis_source
            if not manually_rejected and (
                lead.status in {LeadStatus.ANALYZING, LeadStatus.AI_PENDING, LeadStatus.NOT_LEAD}
                or (lead.status == LeadStatus.NEW and lead.assigned_manager_telegram_id is None)
            ):
                lead.status = LeadStatus.NEW if analysis.is_lead else LeadStatus.NOT_LEAD
            contact.current_lead_score = max(contact.current_lead_score, analysis.lead_score)
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
                        manager_is_lead=False if manually_rejected else None,
                        actual_outcome=LeadStatus.NOT_LEAD.value if manually_rejected else None,
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
                    "factors": analysis.factors.model_dump(),
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
                        .where(
                            Lead.id.is_(None),
                            fresh_signal_clause(max_age_days=self.signal_max_age_days),
                        )
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

    async def list_pending_lead_ids(
        self,
        limit: int = 50,
        *,
        cooldown_seconds: int = 0,
        retry_failed: bool = True,
        exclude_lead_ids: set[int] | None = None,
        local_only: bool = False,
    ) -> list[int]:
        if limit <= 0:
            return []
        cutoff = datetime.now(UTC) - timedelta(seconds=cooldown_seconds)
        stale_analyzing = datetime.now(UTC) - timedelta(
            seconds=max(cooldown_seconds, _STALE_ANALYZING_SECONDS)
        )
        latest_request_status = (
            select(AIRequest.status)
            .where(AIRequest.lead_id == Lead.id)
            .order_by(AIRequest.id.desc())
            .limit(1)
            .scalar_subquery()
        )
        if local_only:
            # A failed API request does not prohibit a free local decision. A
            # claimed request must release ownership before a local retry.
            request_filter = ~select(AIRequest.id).where(
                AIRequest.lead_id == Lead.id,
                AIRequest.status == AIRequestStatus.CLAIMED,
            ).exists()
        else:
            request_filter = or_(latest_request_status.is_(None),
                                 latest_request_status != AIRequestStatus.PERMANENT_FAILURE)
        async with self.session_factory() as session:
            return list(
                await session.scalars(
                    select(Lead.id)
                    .join(Comment, Comment.id == Lead.comment_id)
                    .where(
                        fresh_signal_clause(max_age_days=self.signal_max_age_days),
                        Lead.id.not_in(exclude_lead_ids or set()),
                        request_filter,
                        or_(
                            (
                                (Lead.status == LeadStatus.AI_PENDING)
                                & (True if retry_failed else Lead.ai_attempt_count == 0)
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
                        ),
                    )
                    .order_by(Lead.ai_last_attempt_at.asc(), Lead.created_at, Lead.id)
                    .limit(limit)
                )
            )

    async def list_reanalyze_lead_ids(
        self,
        limit: int = 50,
        *,
        include_not_lead_high_score: bool = False,
        min_not_lead_score: int = 50,
    ) -> list[int]:
        """Свежие лиды NEW/AI_PENDING или спорные NOT_LEAD для переоценки."""
        if limit <= 0:
            return []
        statuses = [LeadStatus.NEW, LeadStatus.AI_PENDING, LeadStatus.ANALYZING]
        if include_not_lead_high_score:
            statuses.append(LeadStatus.NOT_LEAD)
        async with self.session_factory() as session:
            stmt = (
                select(Lead.id)
                .join(Comment, Comment.id == Lead.comment_id)
                .where(
                    fresh_signal_clause(max_age_days=self.signal_max_age_days),
                    Lead.status.in_(statuses),
                )
            )
            if include_not_lead_high_score:
                stmt = stmt.where(
                    or_(
                        Lead.status != LeadStatus.NOT_LEAD,
                        Lead.lead_score >= min_not_lead_score,
                    )
                )
            return list(
                await session.scalars(
                    stmt.order_by(Lead.lead_score.desc(), Lead.updated_at.asc()).limit(limit)
                )
            )

    async def reanalyze_batch(
        self,
        limit: int = 25,
        *,
        include_not_lead_high_score: bool = False,
        min_not_lead_score: int = 50,
    ) -> list[ProcessedLead]:
        """Повторный полный analyze_lead для накопившихся лидов."""
        lead_ids = await self.list_reanalyze_lead_ids(
            limit,
            include_not_lead_high_score=include_not_lead_high_score,
            min_not_lead_score=min_not_lead_score,
        )
        results: list[ProcessedLead] = []
        for lead_id in lead_ids:
            try:
                results.append(await self.analyze_lead(lead_id))
            except Exception:
                logger.exception("reanalyze_batch_failed lead_id=%s", lead_id)
        return results

    async def retry_pending(
        self,
        limit: int = 50,
        *,
        cooldown_seconds: int = 0,
    ) -> list[ProcessedLead]:
        if limit <= 0:
            return []
        lead_ids = await self.list_pending_lead_ids(limit, cooldown_seconds=cooldown_seconds)
        results: list[ProcessedLead] = []
        for lead_id in lead_ids:
            result = await self._retry_pending_one(lead_id)
            if result is not None:
                results.append(result)
        return results

    async def retry_pending_lead(self, lead_id: int) -> ProcessedLead | None:
        """Повторный разбор одного AI_PENDING/ANALYZING лида тем же analyzer, что и batch retry."""
        return await self._retry_pending_one(lead_id)

    async def repair_price_acknowledgements(self, *, dry_run: bool = True) -> dict:
        """Locally repair unassigned NEW acknowledgements; retries skip repaired rows."""
        async with self.session_factory() as session:
            rows = (await session.execute(
                select(Lead.id, Comment.text)
                .join(Comment, Comment.id == Lead.comment_id)
                .where(Lead.status == LeadStatus.NEW, Lead.assigned_manager_telegram_id.is_(None))
                .order_by(Lead.id)
            )).all()
        matched = [lead_id for lead_id, text in rows
                   if RuleBasedLeadAnalyzer.is_price_acknowledgement(text)]
        repaired = []
        if not dry_run:
            for lead_id in matched:
                # Manager choices made since preview still take precedence.
                async with self.session_factory() as session:
                    lead = await session.get(Lead, lead_id)
                    if lead is None or lead.status != LeadStatus.NEW or lead.assigned_manager_telegram_id is not None:
                        continue
                result = await self.analyze_lead(lead_id, local_only=True)
                if result.status == LeadStatus.NOT_LEAD:
                    repaired.append(lead_id)
        return {"dry_run": dry_run, "matched": matched, "repaired": repaired}

    async def repair_assortment(self, *, dry_run: bool = True) -> dict:
        """Apply the owner's scope to saved facts without AI, providers or notifications."""
        updated, excluded, review, pending_contacts = [], [], [], set()
        async with self.session_factory() as session:
            leads = list(await session.scalars(select(Lead).where(
                Lead.vertical == "FURNITURE",
                Lead.status.notin_([LeadStatus.AI_PENDING, LeadStatus.ANALYZING]),
            ).order_by(Lead.id)))
            for lead in leads:
                context = await self._build_context(session, lead.comment_id)
                decision = assess_assortment(context.comment, context.post_caption, context.parent_comment)
                before = dict(lead.analysis_details or {})
                details = dict(before)
                details["assortment"] = decision.as_dict()
                product = resolve_product_context(context.comment, context.post_caption, context.parent_comment)
                category = product.category if product.categories else lead.product_category
                if not product.categories and category == "RAW_RATTAN" and context.vertical == "FURNITURE":
                    category = None  # A previous raw-material guess is not a fact about finished furniture.
                    details["product_category"] = None
                if product.categories:
                    details["product_context"] = product.as_dict()
                    details["product_category"] = category
                if decision.status in {"EXCLUDED", "REVIEW"}:
                    existing = LeadAnalysis(
                        is_lead=lead.status != LeadStatus.NOT_LEAD, lead_score=lead.lead_score,
                        intent=Intent(lead.intent), product_category=category, language=lead.language or "ru",
                        reason=lead.ai_reason or "", confidence=int(details.get("confidence") or 50),
                    )
                    corrected = apply_assortment(existing, decision)
                    if decision.status == "EXCLUDED" or existing.is_lead:
                        for field in ("is_lead", "lead_score", "priority_score", "fit_score", "confidence",
                                      "is_commercial", "commercial_quality", "commercial_stage", "funnel_stage",
                                      "urgency", "reason", "short_reason", "recommended_action", "next_best_action"):
                            details[field] = corrected.model_dump(mode="json")[field]
                        details["risk_flags"] = list(dict.fromkeys([
                            *corrected.risk_flags, *(before.get("risk_flags") or []),
                        ]))[:6]
                        factors = dict(details.get("factors") or {})
                        factors.update(fit_score=0, priority_score=corrected.lead_score)
                        details["factors"] = factors
                if details.get("assortment_audience_pending"):
                    pending_contacts.add(lead.contact_id)
                if details == before and category == lead.product_category:
                    continue
                updated.append(lead.id)
                if decision.status == "EXCLUDED":
                    excluded.append(lead.id)
                elif decision.status == "REVIEW":
                    review.append(lead.id)
                if dry_run:
                    continue
                previous_score = lead.lead_score
                lead.product_category = category
                if decision.status in {"EXCLUDED", "REVIEW"} and (decision.status == "EXCLUDED" or lead.status != LeadStatus.NOT_LEAD):
                    lead.lead_score = int(details["lead_score"])
                    lead.ai_reason = decision.reason
                if decision.status == "EXCLUDED" and lead.status == LeadStatus.NEW and lead.assigned_manager_telegram_id is None:
                    lead.status = LeadStatus.NOT_LEAD
                details["assortment_audience_pending"] = self.audience_engine is not None
                lead.analysis_details = details
                await ContactEventRepository(session).add(
                    lead.contact_id, ContactEventType.QUALIFICATION_UPDATED, lead_id=lead.id,
                    payload={"source": "assortment_repair", "assortment": decision.as_dict(),
                             "from": previous_score, "to": lead.lead_score},
                )
                if self.audience_engine is not None:
                    pending_contacts.add(lead.contact_id)
            if not dry_run:
                await session.commit()
        if not dry_run and self.audience_engine is not None:
            for contact_id in sorted(pending_contacts):
                await self.audience_engine.recalculate_contact(contact_id)
                async with self.session_factory() as session:
                    for lead in await session.scalars(select(Lead).where(Lead.contact_id == contact_id)):
                        details = dict(lead.analysis_details or {})
                        if details.get("assortment_audience_pending"):
                            details["assortment_audience_pending"] = False
                            lead.analysis_details = details
                    await session.commit()
            pending_contacts.clear()
        return {"dry_run": dry_run, "updated": updated, "excluded": excluded,
                "review": review, "pending_contacts": sorted(pending_contacts) if not dry_run else []}

    async def repair_product_contexts(self, limit: int = 500) -> dict:
        """Correct stored product facts locally, retaining scores and workflow decisions."""
        async with self.session_factory() as session:
            ids = list(await session.scalars(select(Lead.id).where(
                Lead.vertical == "FURNITURE",
                Lead.status.notin_([LeadStatus.AI_PENDING, LeadStatus.ANALYZING]),
            ).order_by(Lead.id).limit(max(0, min(limit, 5000)))))
        updated, contacts = [], set()
        for lead_id in ids:
            async with self.session_factory() as session:
                await session.execute(update(Lead).where(Lead.id == lead_id).values(
                    updated_at=Lead.updated_at,
                ))
                lead = await session.get(Lead, lead_id)
                if lead is None:
                    continue
                details = dict(lead.analysis_details or {})
                if (details.get("rattan_taxonomy") or {}).get("layer") == "RAW_MATERIAL":
                    continue
                context = await self._build_context(session, lead.comment_id)
                product = resolve_product_context(
                    context.comment, context.post_caption, context.parent_comment,
                )
                if not product.categories or (
                    product.source == "POST_CAPTION" and product.category is not None
                ):
                    continue
                changed = (
                    lead.product_category != product.category
                    or (product.category == "MIXED_FURNITURE" and (
                        details.get("quantity") is not None
                        or details.get("product_context") != product.as_dict()
                    ))
                )
                if changed:
                    before = lead.product_category
                    lead.product_category = product.category
                    details["product_category"] = product.category
                    details["product_context"] = product.as_dict()
                    if product.category == "MIXED_FURNITURE":
                        details["quantity"] = None
                    evidence = [item for item in details.get("evidence", [])
                                if not str(item).startswith("Товарный контекст:")]
                    if product.category:
                        evidence.append("Товарный контекст: " + ", ".join(product.categories))
                    details["evidence"] = evidence[:6]
                    details["product_context_audience_pending"] = self.audience_engine is not None
                    lead.analysis_details = details
                    await ContactEventRepository(session).add(
                        lead.contact_id, ContactEventType.QUALIFICATION_UPDATED, lead_id=lead.id,
                        payload={"reason": "Уточнён товар по публичному комментарию и его контексту.",
                                 "product_category_before": before,
                                 "product_category": product.category,
                                 "product_context": product.as_dict()},
                    )
                    updated.append(lead.id)
                if details.get("product_context_audience_pending"):
                    contacts.add(lead.contact_id)
                await session.commit()
        recalculated, pending = [], []
        if self.audience_engine is not None:
            for contact_id in sorted(contacts):
                try:
                    await self.audience_engine.recalculate_contact(contact_id)
                    async with self.session_factory() as session:
                        await session.execute(update(Lead).where(Lead.contact_id == contact_id).values(
                            updated_at=Lead.updated_at,
                        ))
                        for lead in await session.scalars(select(Lead).where(Lead.contact_id == contact_id)):
                            details = dict(lead.analysis_details or {})
                            if details.get("product_context_audience_pending"):
                                details["product_context_audience_pending"] = False
                                lead.analysis_details = details
                        await session.commit()
                    recalculated.append(contact_id)
                except Exception:
                    logger.exception("product_context_audience_repair_failed contact_id=%s", contact_id)
                    pending.append(contact_id)
        return {"updated": updated, "contacts_recalculated": recalculated, "pending_contacts": pending}

    @staticmethod
    async def _has_claimed_ai_request(session: AsyncSession, lead_id: int) -> bool:
        return await session.scalar(select(AIRequest.id).where(
            AIRequest.lead_id == lead_id, AIRequest.status == AIRequestStatus.CLAIMED,
        ).limit(1)) is not None

    async def retry_pending_local(self, limit: int = 100) -> list[ProcessedLead]:
        """Recover only locally decidable pending signals without invoking any paid analyzer."""
        lead_ids = await self.list_pending_lead_ids(limit, cooldown_seconds=0, local_only=True)
        results: list[ProcessedLead] = []
        for lead_id in lead_ids:
            async with self.session_factory() as session:
                lead = await session.get(Lead, lead_id)
                if lead is None or lead.status not in {LeadStatus.AI_PENDING, LeadStatus.ANALYZING}:
                    continue
            result = await self.analyze_lead(lead_id, local_only=True, pending_only=True)
            if result.status not in {LeadStatus.AI_PENDING, LeadStatus.ANALYZING}:
                results.append(result)
        return results

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
                or not assortment_eligible(details)
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
            parent_comment=(comment.parent_comment_text or "").strip(),
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
            source_vertical=competitor.vertical.value if competitor.active else None,
        )

    async def _analyze(self, context: LeadAnalysisContext):
        analyze_with_source = getattr(self.analyzer, "analyze_with_source", None)
        if analyze_with_source is not None:
            return await analyze_with_source(context)
        return await self.analyzer.analyze(context), "custom_analyzer"

    async def _signal_is_fresh(self, comment_id: int) -> bool:
        async with self.session_factory() as session:
            comment = await session.get(Comment, comment_id)
            if comment is None:
                return False
            return is_signal_within_window(
                signal_observed_at(
                    created_at_platform=comment.created_at_platform,
                    discovered_at=comment.discovered_at,
                ),
                max_age_days=self.signal_max_age_days,
            )

    def _to_result(self, lead: Lead, *, created: bool) -> ProcessedLead:
        return ProcessedLead(
            lead_id=lead.id,
            score=lead.lead_score,
            status=lead.status,
            created=created,
            is_hot=(
                lead.lead_score >= self.hot_threshold
                and assortment_eligible(lead.analysis_details)
                and lead.status not in {LeadStatus.NOT_LEAD, LeadStatus.LOST}
            ),
        )
