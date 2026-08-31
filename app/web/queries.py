from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from itertools import combinations

from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import (
    AIFeedback,
    AIRequest,
    AIRequestStatus,
    AudienceMembership,
    AudienceSegment,
    Comment,
    Competitor,
    Contact,
    ContactEvent,
    ContactEventType,
    ContactIntelligence,
    ContactTask,
    CostEvent,
    Deal,
    DealSaleSnapshot,
    DealStatus,
    Evidence,
    ExternalBudgetReservation,
    ExternalUsage,
    Lead,
    LeadStatus,
    MarketCandidate,
    MonitorRun,
    NotificationLog,
    NotificationStatus,
    Post,
    Product,
    PublicSignal,
    ReservationStatus,
    SignificantChange,
    SignificantChangeNotification,
    TaskStatus,
    Vertical,
)
from app.services.audience_facet_service import AudienceFacetQuery
from app.services.audience_quality_service import AudienceQualityService
from app.services.economics_page_service import EconomicsPageService
from app.services.product_catalog_service import normalize_product_category

OPEN_LEAD_STATUSES = [
    LeadStatus.ANALYZING,
    LeadStatus.AI_PENDING,
    LeadStatus.NEW,
    LeadStatus.TAKEN,
    LeadStatus.CONTACTED,
    LeadStatus.QUALIFIED,
    LeadStatus.OFFER_SENT,
    LeadStatus.NEGOTIATION,
]

CONFIRMED_LEAD_STATUSES = [
    LeadStatus.NEW,
    LeadStatus.TAKEN,
    LeadStatus.CONTACTED,
    LeadStatus.QUALIFIED,
    LeadStatus.OFFER_SENT,
    LeadStatus.NEGOTIATION,
    LeadStatus.WON,
    LeadStatus.LOST,
]


class WebQueryService:
    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], hot_threshold: int
    ) -> None:
        self.session_factory = session_factory
        self.hot_threshold = hot_threshold

    async def ai_safety_diagnostics(self) -> dict:
        now = datetime.now(UTC)
        async with self.session_factory() as session:
            status_rows = (
                await session.execute(
                    select(AIRequest.status, func.count(AIRequest.id)).group_by(AIRequest.status)
                )
            ).all()
            active_reservations = await session.scalar(
                select(func.count(ExternalBudgetReservation.id)).where(
                    ExternalBudgetReservation.status == ReservationStatus.RESERVED,
                    ExternalBudgetReservation.expires_at > now,
                )
            )
            stale_ai_leases = await session.scalar(
                select(func.count(AIRequest.id)).where(
                    AIRequest.status == AIRequestStatus.CLAIMED,
                    AIRequest.claim_expires_at <= now,
                )
            )
            uncertain_reservations = await session.scalar(
                select(func.count(ExternalBudgetReservation.id)).where(
                    ExternalBudgetReservation.status == ReservationStatus.EXPIRED,
                    ExternalBudgetReservation.call_started_at.is_not(None),
                )
            )
        return {
            "statuses": {status.value: count for status, count in status_rows},
            "active_reservations": int(active_reservations or 0),
            "stale_ai_leases": int(stale_ai_leases or 0),
            "uncertain_reservations": int(uncertain_reservations or 0),
            "cost_events": int(await self._scalar_count(CostEvent.id)),
        }

    async def _scalar_count(self, column) -> int:
        async with self.session_factory() as session:
            return int(await session.scalar(select(func.count(column))) or 0)

    async def rattan_workspace(self) -> dict:
        """Rattan portfolio: only sources with explicit Competitor.vertical enrollment."""
        async with self.session_factory() as session:
            enrolled = list(
                await session.scalars(
                    select(Competitor)
                    .where(Competitor.vertical == Vertical.ARTIFICIAL_RATTAN)
                    .order_by(Competitor.normalized_handle)
                )
            )
            enrolled_ids = [item.id for item in enrolled]
            context_signal_count = 0
            commercial_signal_count = 0
            rows: list = []
            if enrolled_ids:
                context_signal_count = int(
                    await session.scalar(
                        select(func.count(Lead.id)).where(
                            Lead.vertical == Vertical.ARTIFICIAL_RATTAN,
                            Lead.competitor_id.in_(enrolled_ids),
                        )
                    )
                    or 0
                )
                commercial_signal_count = int(
                    await session.scalar(
                        select(func.count(Lead.id)).where(
                            Lead.vertical == Vertical.ARTIFICIAL_RATTAN,
                            Lead.competitor_id.in_(enrolled_ids),
                            Lead.status.in_(CONFIRMED_LEAD_STATUSES),
                        )
                    )
                    or 0
                )
                rows = (
                    await session.execute(
                        select(Lead, Comment, Contact, Competitor, PublicSignal, Evidence)
                        .join(Comment, Comment.id == Lead.comment_id)
                        .join(Contact, Contact.id == Lead.contact_id)
                        .join(Competitor, Competitor.id == Lead.competitor_id)
                        .join(PublicSignal, PublicSignal.comment_id == Comment.id)
                        .join(Evidence, Evidence.public_signal_id == PublicSignal.id)
                        .where(
                            Lead.vertical == Vertical.ARTIFICIAL_RATTAN,
                            Lead.competitor_id.in_(enrolled_ids),
                            Lead.status.in_(CONFIRMED_LEAD_STATUSES),
                        )
                        .order_by(desc(Comment.discovered_at))
                        .limit(100)
                    )
                ).all()
            orphan_rattan_signals = int(
                await session.scalar(
                    select(func.count(Lead.id))
                    .join(Competitor, Competitor.id == Lead.competitor_id)
                    .where(
                        Lead.vertical == Vertical.ARTIFICIAL_RATTAN,
                        Competitor.vertical != Vertical.ARTIFICIAL_RATTAN,
                    )
                )
                or 0
            )
        layers: Counter[str] = Counter()
        roles: Counter[str] = Counter()
        products: Counter[str] = Counter()
        for _lead, _comment, _contact, _competitor, _signal, evidence in rows:
            taxonomy = (evidence.raw_data or {}).get("rattan_taxonomy") or {}
            if taxonomy.get("layer"):
                layers[str(taxonomy["layer"])] += 1
            if taxonomy.get("role") and taxonomy.get("role") != "UNKNOWN":
                roles[str(taxonomy["role"])] += 1
            products.update(str(item) for item in taxonomy.get("products") or [])
        return {
            "rattan_rows": rows,
            "rattan_companies": enrolled,
            "rattan_layers": layers,
            "rattan_roles": roles.most_common(),
            "rattan_products": products.most_common(),
            "rattan_counts": {
                "signals": commercial_signal_count,
                "filtered_noise": max(0, context_signal_count - commercial_signal_count),
                "companies": len(enrolled),
                "raw": layers.get("RAW_MATERIAL", 0),
                "ready": layers.get("READY_FURNITURE", 0),
                "orphan_rattan_signals": orphan_rattan_signals,
                "portfolio_empty": len(enrolled) == 0,
            },
        }

    async def dashboard(self) -> dict:
        now = datetime.now(UTC)
        last_24h = now - timedelta(hours=24)
        async with self.session_factory() as session:
            counts = {
                "contacts": await self._count(session, Contact),
                "comments": await self._count(session, Comment),
                "posts": await self._count(session, Post),
                "competitors": await self._count(session, Competitor),
                "leads": await self._count(session, Lead),
                "deals": await self._count(session, Deal),
            }
            counts["new_comments_24h"] = int(
                await session.scalar(
                    select(func.count(Comment.id)).where(Comment.discovered_at >= last_24h)
                )
                or 0
            )
            counts["analyzed"] = int(
                await session.scalar(
                    select(func.count(Lead.id)).where(
                        Lead.status.not_in([LeadStatus.ANALYZING, LeadStatus.AI_PENDING])
                    )
                )
                or 0
            )
            counts["ai_pending"] = int(
                await session.scalar(
                    select(func.count(Lead.id)).where(
                        Lead.status.in_([LeadStatus.ANALYZING, LeadStatus.AI_PENDING])
                    )
                )
                or 0
            )
            counts["unprocessed"] = int(
                await session.scalar(
                    select(func.count(Comment.id))
                    .outerjoin(Lead, Lead.comment_id == Comment.id)
                    .where(Lead.id.is_(None))
                )
                or 0
            )
            counts["notifications_pending"] = int(
                await session.scalar(
                    select(func.count(NotificationLog.id)).where(
                        NotificationLog.status.in_(
                            [NotificationStatus.PENDING, NotificationStatus.PROCESSING]
                        )
                    )
                )
                or 0
            )
            counts["notifications_pending"] += int(
                await session.scalar(
                    select(func.count(SignificantChangeNotification.id)).where(
                        SignificantChangeNotification.status.in_(
                            [NotificationStatus.PENDING, NotificationStatus.PROCESSING]
                        )
                    )
                )
                or 0
            )
            counts["notifications_failed"] = int(
                await session.scalar(
                    select(func.count(NotificationLog.id)).where(
                        NotificationLog.status == NotificationStatus.FAILED
                    )
                )
                or 0
            )
            counts["notifications_failed"] += int(
                await session.scalar(
                    select(func.count(SignificantChangeNotification.id)).where(
                        SignificantChangeNotification.status == NotificationStatus.FAILED
                    )
                )
                or 0
            )
            counts["notifications_uncertain"] = int(
                await session.scalar(
                    select(func.count(NotificationLog.id)).where(
                        NotificationLog.status == NotificationStatus.UNCERTAIN
                    )
                )
                or 0
            )
            counts["notifications_uncertain"] += int(
                await session.scalar(
                    select(func.count(SignificantChangeNotification.id)).where(
                        SignificantChangeNotification.status == NotificationStatus.UNCERTAIN
                    )
                )
                or 0
            )
            counts["significant_changes_24h"] = int(
                await session.scalar(
                    select(func.count(SignificantChange.id)).where(
                        SignificantChange.created_at >= last_24h
                    )
                )
                or 0
            )
            counts["hot"] = int(
                await session.scalar(
                    select(func.count(Lead.id)).where(
                        Lead.lead_score >= self.hot_threshold,
                        Lead.status.not_in([LeadStatus.NOT_LEAD, LeadStatus.LOST]),
                    )
                )
                or 0
            )
            counts["open"] = int(
                await session.scalar(
                    select(func.count(Lead.id)).where(Lead.status.in_(OPEN_LEAD_STATUSES))
                )
                or 0
            )
            counts["won"] = int(
                await session.scalar(
                    select(func.count(Deal.id)).where(Deal.status == DealStatus.WON)
                )
                or 0
            )
            snapshot_count = int(
                await session.scalar(
                    select(func.count(DealSaleSnapshot.id)).where(
                        DealSaleSnapshot.sale_currency == "UZS"
                    )
                )
                or 0
            )
            counts["revenue"] = (
                await session.scalar(
                    select(func.sum(DealSaleSnapshot.sale_amount)).where(
                        DealSaleSnapshot.sale_currency == "UZS"
                    )
                )
                if snapshot_count == counts["won"]
                else None
            )
            counts["tasks_due"] = int(
                await session.scalar(
                    select(func.count(ContactTask.id)).where(
                        ContactTask.status == TaskStatus.OPEN,
                        ContactTask.due_at <= now,
                    )
                )
                or 0
            )
            counts["tasks_today"] = int(
                await session.scalar(
                    select(func.count(ContactTask.id)).where(
                        ContactTask.status == TaskStatus.OPEN,
                        ContactTask.due_at <= now + timedelta(hours=24),
                    )
                )
                or 0
            )

            recent_signals = (
                await session.execute(
                    select(Comment, Contact, Competitor, Post, Lead)
                    .join(Contact, Contact.id == Comment.contact_id)
                    .join(Competitor, Competitor.id == Comment.competitor_id)
                    .join(Post, Post.id == Comment.post_id)
                    .outerjoin(Lead, Lead.comment_id == Comment.id)
                    .order_by(desc(Comment.discovered_at))
                    .limit(8)
                )
            ).all()
            hot_leads = (
                await session.execute(
                    select(Lead, Contact, Comment, Competitor)
                    .join(Contact, Contact.id == Lead.contact_id)
                    .join(Comment, Comment.id == Lead.comment_id)
                    .join(Competitor, Competitor.id == Lead.competitor_id)
                    .where(
                        Lead.lead_score >= self.hot_threshold,
                        Lead.status.in_(OPEN_LEAD_STATUSES),
                    )
                    .order_by(desc(Lead.lead_score), desc(Lead.created_at))
                    .limit(6)
                )
            ).all()
            recent_changes = (
                await session.execute(
                    select(SignificantChange, Contact, Lead)
                    .join(Contact, Contact.id == SignificantChange.contact_id)
                    .join(Lead, Lead.id == SignificantChange.lead_id)
                    .order_by(desc(SignificantChange.created_at))
                    .limit(6)
                )
            ).all()
            tasks = (
                await session.execute(
                    select(ContactTask, Contact, Lead)
                    .join(Contact, Contact.id == ContactTask.contact_id)
                    .outerjoin(Lead, Lead.id == ContactTask.lead_id)
                    .where(ContactTask.status == TaskStatus.OPEN)
                    .order_by(ContactTask.due_at)
                    .limit(8)
                )
            ).all()
            recent_runs = (
                await session.scalars(
                    select(MonitorRun).order_by(desc(MonitorRun.started_at)).limit(5)
                )
            ).all()
            coverage = (
                await session.execute(
                    select(Post.coverage_status, func.count(Post.id)).group_by(Post.coverage_status)
                )
            ).all()
            funnel_rows = (
                await session.execute(
                    select(Lead.status, func.count(Lead.id)).group_by(Lead.status)
                )
            ).all()
        return {
            "counts": counts,
            "recent_signals": recent_signals,
            "hot_leads": hot_leads,
            "recent_changes": recent_changes,
            "tasks": tasks,
            "recent_runs": recent_runs,
            "coverage": {getattr(key, "value", str(key)): value for key, value in coverage},
            "funnel": {getattr(key, "value", str(key)): value for key, value in funnel_rows},
        }

    async def signal_overview(self) -> dict[str, int]:
        async with self.session_factory() as session:
            total = int(await session.scalar(select(func.count(Comment.id))) or 0)
            unprocessed = int(
                await session.scalar(
                    select(func.count(Comment.id))
                    .outerjoin(Lead, Lead.comment_id == Comment.id)
                    .where(Lead.id.is_(None))
                )
                or 0
            )
            hot = int(
                await session.scalar(
                    select(func.count(Lead.id)).where(
                        Lead.lead_score >= self.hot_threshold,
                        Lead.status.in_(OPEN_LEAD_STATUSES),
                    )
                )
                or 0
            )
            qualified = int(
                await session.scalar(
                    select(func.count(Lead.id)).where(Lead.status.in_(OPEN_LEAD_STATUSES))
                )
                or 0
            )
            rejected = int(
                await session.scalar(
                    select(func.count(Lead.id)).where(Lead.status == LeadStatus.NOT_LEAD)
                )
                or 0
            )
            pending = int(
                await session.scalar(
                    select(func.count(Lead.id)).where(
                        Lead.status.in_([LeadStatus.ANALYZING, LeadStatus.AI_PENDING])
                    )
                )
                or 0
            )
        return {
            "total": total,
            "unprocessed": unprocessed,
            "qualified": qualified,
            "hot": hot,
            "rejected": rejected,
            "pending": pending,
        }

    async def signals(
        self,
        *,
        q: str = "",
        competitor: str = "",
        kind: str = "",
        limit: int = 300,
    ) -> list:
        async with self.session_factory() as session:
            stmt = (
                select(Comment, Contact, Competitor, Post, Lead)
                .join(Contact, Contact.id == Comment.contact_id)
                .join(Competitor, Competitor.id == Comment.competitor_id)
                .join(Post, Post.id == Comment.post_id)
                .outerjoin(Lead, Lead.comment_id == Comment.id)
                .order_by(desc(Comment.discovered_at), desc(Comment.id))
                .limit(limit)
            )
            if q.strip():
                pattern = f"%{q.strip().lower()}%"
                stmt = stmt.where(
                    or_(
                        func.lower(Contact.username).like(pattern),
                        func.lower(func.coalesce(Contact.display_name, "")).like(pattern),
                        func.lower(Comment.text).like(pattern),
                        func.lower(Post.caption).like(pattern),
                        func.lower(func.coalesce(Lead.product_category, "")).like(pattern),
                    )
                )
            if competitor.strip():
                stmt = stmt.where(Competitor.normalized_handle == competitor.strip().lower())
            normalized_kind = kind.strip().lower()
            if normalized_kind == "new":
                stmt = stmt.where(Comment.is_baseline.is_(False))
            elif normalized_kind == "history":
                stmt = stmt.where(Comment.is_baseline.is_(True))
            elif normalized_kind == "hot":
                stmt = stmt.where(Lead.lead_score >= self.hot_threshold)
            elif normalized_kind == "pending":
                stmt = stmt.where(
                    or_(
                        Lead.id.is_(None),
                        Lead.status.in_([LeadStatus.ANALYZING, LeadStatus.AI_PENDING]),
                    )
                )
            return (await session.execute(stmt)).all()

    async def leads(
        self,
        *,
        q: str = "",
        status: str = "",
        contact_id: int | None = None,
        limit: int = 300,
        include_not_leads: bool = False,
    ) -> list:
        async with self.session_factory() as session:
            stmt = (
                select(Lead, Contact, Comment, Competitor, Post, Deal)
                .join(Contact, Contact.id == Lead.contact_id)
                .join(Comment, Comment.id == Lead.comment_id)
                .join(Competitor, Competitor.id == Lead.competitor_id)
                .join(Post, Post.id == Comment.post_id)
                .outerjoin(Deal, Deal.lead_id == Lead.id)
                .order_by(desc(Lead.lead_score), desc(Lead.created_at))
                .limit(limit)
            )
            if q.strip():
                pattern = f"%{q.strip().lower()}%"
                stmt = stmt.where(
                    or_(
                        func.lower(Contact.username).like(pattern),
                        func.lower(func.coalesce(Contact.display_name, "")).like(pattern),
                        func.lower(Comment.text).like(pattern),
                        func.lower(func.coalesce(Lead.product_category, "")).like(pattern),
                        func.lower(Competitor.normalized_handle).like(pattern),
                    )
                )
            if contact_id is not None:
                stmt = stmt.where(Lead.contact_id == contact_id)
            if status.strip():
                try:
                    stmt = stmt.where(Lead.status == LeadStatus(status.strip().upper()))
                except ValueError:
                    return []
            elif not include_not_leads:
                stmt = stmt.where(Lead.status != LeadStatus.NOT_LEAD)
            return (await session.execute(stmt)).all()

    async def lead_detail(self, lead_id: int) -> dict | None:
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    select(Lead, Contact, Comment, Competitor, Post, Deal)
                    .join(Contact, Contact.id == Lead.contact_id)
                    .join(Comment, Comment.id == Lead.comment_id)
                    .join(Competitor, Competitor.id == Lead.competitor_id)
                    .join(Post, Post.id == Comment.post_id)
                    .outerjoin(Deal, Deal.lead_id == Lead.id)
                    .where(Lead.id == lead_id)
                )
            ).one_or_none()
            if row is None:
                return None
            lead, contact, comment, competitor, post, deal = row
            history = (
                await session.execute(
                    select(Comment, Competitor, Post, Lead)
                    .join(Competitor, Competitor.id == Comment.competitor_id)
                    .join(Post, Post.id == Comment.post_id)
                    .outerjoin(Lead, Lead.comment_id == Comment.id)
                    .where(Comment.contact_id == contact.id)
                    .order_by(desc(Comment.discovered_at))
                    .limit(20)
                )
            ).all()
            tasks = (
                await session.scalars(
                    select(ContactTask)
                    .where(
                        ContactTask.contact_id == contact.id,
                        ContactTask.status == TaskStatus.OPEN,
                    )
                    .order_by(ContactTask.due_at)
                )
            ).all()
            return {
                "lead": lead,
                "contact": contact,
                "comment": comment,
                "competitor": competitor,
                "post": post,
                "deal": deal,
                "history": history,
                "tasks": tasks,
            }

    async def contacts(self, *, q: str = "", limit: int = 300) -> list:
        async with self.session_factory() as session:
            lead_stats = (
                select(
                    Lead.contact_id.label("contact_id"),
                    func.max(Lead.lead_score).label("max_score"),
                    func.count(Lead.id).label("lead_count"),
                )
                .group_by(Lead.contact_id)
                .subquery()
            )
            signal_stats = (
                select(
                    Comment.contact_id.label("contact_id"),
                    func.count(Comment.id).label("signal_count"),
                )
                .group_by(Comment.contact_id)
                .subquery()
            )
            source_stats = (
                select(
                    Comment.contact_id.label("contact_id"),
                    func.count(func.distinct(Comment.competitor_id)).label("source_count"),
                )
                .group_by(Comment.contact_id)
                .subquery()
            )
            task_stats = (
                select(
                    ContactTask.contact_id.label("contact_id"),
                    func.count(ContactTask.id).label("task_count"),
                )
                .where(ContactTask.status == TaskStatus.OPEN)
                .group_by(ContactTask.contact_id)
                .subquery()
            )
            stmt = (
                select(
                    Contact,
                    func.coalesce(signal_stats.c.signal_count, 0),
                    func.coalesce(source_stats.c.source_count, 0),
                    func.coalesce(lead_stats.c.lead_count, 0),
                    func.coalesce(lead_stats.c.max_score, 0),
                    func.coalesce(task_stats.c.task_count, 0),
                )
                .outerjoin(signal_stats, signal_stats.c.contact_id == Contact.id)
                .outerjoin(source_stats, source_stats.c.contact_id == Contact.id)
                .outerjoin(lead_stats, lead_stats.c.contact_id == Contact.id)
                .outerjoin(task_stats, task_stats.c.contact_id == Contact.id)
                .order_by(desc(Contact.last_seen_at))
                .limit(limit)
            )
            if q.strip():
                pattern = f"%{q.strip().lower()}%"
                stmt = stmt.where(
                    or_(
                        func.lower(Contact.username).like(pattern),
                        func.lower(func.coalesce(Contact.display_name, "")).like(pattern),
                    )
                )
            return (await session.execute(stmt)).all()

    async def contact_detail(self, contact_id: int) -> dict | None:
        async with self.session_factory() as session:
            contact = await session.get(Contact, contact_id)
            if contact is None:
                return None
            signals = (
                await session.execute(
                    select(Comment, Competitor, Post, Lead)
                    .join(Competitor, Competitor.id == Comment.competitor_id)
                    .join(Post, Post.id == Comment.post_id)
                    .outerjoin(Lead, Lead.comment_id == Comment.id)
                    .where(Comment.contact_id == contact_id)
                    .order_by(desc(Comment.created_at_platform), desc(Comment.discovered_at))
                )
            ).all()
            events = (
                await session.scalars(
                    select(ContactEvent)
                    .where(ContactEvent.contact_id == contact_id)
                    .order_by(desc(ContactEvent.created_at))
                    .limit(150)
                )
            ).all()
            deals = (
                await session.scalars(
                    select(Deal)
                    .where(Deal.contact_id == contact_id)
                    .order_by(desc(Deal.created_at))
                )
            ).all()
            leads = (
                await session.scalars(
                    select(Lead)
                    .where(Lead.contact_id == contact_id)
                    .order_by(desc(Lead.created_at))
                )
            ).all()
            tasks = (
                await session.scalars(
                    select(ContactTask)
                    .where(ContactTask.contact_id == contact_id)
                    .order_by(ContactTask.status, ContactTask.due_at)
                )
            ).all()
            notes = [
                event
                for event in events
                if event.event_type == ContactEventType.NOTE_ADDED
                and event.payload_json.get("text")
            ]
            source_handles = sorted(
                {competitor.normalized_handle for _comment, competitor, _post, _lead in signals}
            )
            intelligence = await session.scalar(
                select(ContactIntelligence).where(ContactIntelligence.contact_id == contact_id)
            )
            audiences = (
                await session.execute(
                    select(AudienceMembership, AudienceSegment)
                    .join(AudienceSegment, AudienceSegment.id == AudienceMembership.segment_id)
                    .where(
                        AudienceMembership.contact_id == contact_id,
                        AudienceMembership.active.is_(True),
                    )
                    .order_by(AudienceSegment.name)
                )
            ).all()
            significant_changes = list(
                await session.scalars(
                    select(SignificantChange)
                    .where(SignificantChange.contact_id == contact_id)
                    .order_by(desc(SignificantChange.created_at))
                    .limit(30)
                )
            )
            return {
                "contact": contact,
                "signals": signals,
                "events": events,
                "deals": deals,
                "leads": leads,
                "tasks": tasks,
                "notes": notes,
                "source_handles": source_handles,
                "source_count": len(source_handles),
                "intelligence": intelligence,
                "audiences": audiences,
                "significant_changes": significant_changes,
            }

    async def audiences(self, vertical: str = "FURNITURE") -> list[dict]:
        quality = await AudienceQualityService(self.session_factory).snapshot(vertical)
        health_by_slug = {row.segment_slug: row for row in quality.health_rows}
        async with self.session_factory() as session:
            try:
                selected_vertical = Vertical(vertical)
            except ValueError:
                selected_vertical = Vertical.FURNITURE
            segments = list(
                await session.scalars(
                    select(AudienceSegment)
                    .where(
                        AudienceSegment.active.is_(True),
                        AudienceSegment.status == "ACTIVE",
                        AudienceSegment.vertical == selected_vertical,
                    )
                    .order_by(AudienceSegment.name)
                )
            )
            result: list[dict] = []
            for segment in segments:
                members = (
                    (
                        await session.execute(
                            select(ContactIntelligence)
                            .join(
                                AudienceMembership,
                                AudienceMembership.contact_id == ContactIntelligence.contact_id,
                            )
                            .where(
                                AudienceMembership.segment_id == segment.id,
                                AudienceMembership.active.is_(True),
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                product_counts: Counter[str] = Counter()
                intent_counts: Counter[str] = Counter()
                for item in members:
                    product_counts.update(
                        {
                            str(row["value"]): int(row["count"])
                            for row in item.product_interests_json
                        }
                    )
                    intent_counts.update(
                        {str(row["value"]): int(row["count"]) for row in item.top_intents_json}
                    )
                result.append(
                    {
                        "segment": segment,
                        "members": len(members),
                        "avg_activity": round(
                            sum(item.activity_score for item in members) / len(members)
                        )
                        if members
                        else 0,
                        "avg_value": round(sum(item.value_score for item in members) / len(members))
                        if members
                        else 0,
                        "top_product": product_counts.most_common(1)[0][0]
                        if product_counts
                        else None,
                        "top_intent": intent_counts.most_common(1)[0][0] if intent_counts else None,
                        "health": health_by_slug.get(segment.slug),
                    }
                )
            return result

    async def audience_quality(self, vertical: str = "FURNITURE") -> dict:
        page = await AudienceQualityService(self.session_factory).snapshot(vertical)
        return {"page": page}

    async def audience_detail(
        self, slug: str, facets: AudienceFacetQuery | None = None
    ) -> dict | None:
        async with self.session_factory() as session:
            segment = await session.scalar(
                select(AudienceSegment).where(
                    AudienceSegment.slug == slug,
                    AudienceSegment.active.is_(True),
                    AudienceSegment.status == "ACTIVE",
                )
            )
            if segment is None:
                return None
            member_rows = (
                await session.execute(
                    select(AudienceMembership, Contact, ContactIntelligence)
                    .join(Contact, Contact.id == AudienceMembership.contact_id)
                    .join(
                        ContactIntelligence,
                        ContactIntelligence.contact_id == AudienceMembership.contact_id,
                    )
                    .where(
                        AudienceMembership.segment_id == segment.id,
                        AudienceMembership.active.is_(True),
                    )
                    .order_by(desc(ContactIntelligence.value_score))
                )
            ).all()
            contact_ids = [contact.id for _membership, contact, _intel in member_rows]
            leads = []
            if contact_ids:
                leads = (
                    await session.execute(
                        select(Lead, Comment, Competitor)
                        .join(Comment, Comment.id == Lead.comment_id)
                        .join(Competitor, Competitor.id == Lead.competitor_id)
                        .where(Lead.contact_id.in_(contact_ids))
                    )
                ).all()
            facet_query = facets or AudienceFacetQuery()
            won_rows = (
                (
                    await session.execute(
                        select(Deal.contact_id, Deal.status).where(Deal.contact_id.in_(contact_ids))
                    )
                ).all()
                if contact_ids
                else []
            )
            won_by_contact: dict[int, set[str]] = {}
            for contact_id, status in won_rows:
                won_by_contact.setdefault(contact_id, set()).add(str(status))
            leads_by_contact: dict[int, list[tuple[Lead, Comment, Competitor]]] = {}
            for row in leads:
                leads_by_contact.setdefault(row[0].contact_id, []).append(row)
            member_rows = [
                (membership, contact, intelligence)
                for membership, contact, intelligence in member_rows
                if facet_query.matches(
                    membership,
                    contact,
                    intelligence,
                    source_competitors={
                        competitor.normalized_handle
                        for _lead, _comment, competitor in leads_by_contact.get(contact.id, [])
                    },
                    rattan_layers={
                        str((lead.analysis_details or {}).get("rattan_taxonomy", {}).get("layer"))
                        for lead, _comment, _competitor in leads_by_contact.get(contact.id, [])
                        if (lead.analysis_details or {}).get("rattan_taxonomy", {}).get("layer")
                    },
                    rattan_roles={
                        str((lead.analysis_details or {}).get("rattan_taxonomy", {}).get("role"))
                        for lead, _comment, _competitor in leads_by_contact.get(contact.id, [])
                        if (lead.analysis_details or {}).get("rattan_taxonomy", {}).get("role")
                    },
                    won_statuses=won_by_contact.get(contact.id, set()),
                )
            ]
            filtered_contact_ids = {contact.id for _membership, contact, _intel in member_rows}
            leads = [row for row in leads if row[0].contact_id in filtered_contact_ids]
            intents = Counter(lead.intent for lead, _comment, _competitor in leads)
            products = Counter(
                lead.product_category
                for lead, _comment, _competitor in leads
                if lead.product_category
            )
            competitors = Counter(
                competitor.normalized_handle for _lead, _comment, competitor in leads
            )
            objections: Counter[str] = Counter()
            for lead, _comment, _competitor in leads:
                objections.update((lead.analysis_details or {}).get("risk_flags") or [])
            top_product = products.most_common(1)[0][0] if products else None
            offer, message, landing = self._campaign_recommendation(
                top_product,
                intents.most_common(1)[0][0] if intents else None,
            )
            return {
                "segment": segment,
                "members": member_rows,
                "top_intents": intents.most_common(5),
                "top_products": products.most_common(5),
                "top_competitors": competitors.most_common(5),
                "objections": objections.most_common(5),
                "campaign_offer": offer,
                "campaign_message": message,
                "landing_recommendation": landing,
                "facets": facet_query,
            }

    @staticmethod
    def _campaign_recommendation(product: str | None, intent: str | None):
        product_names = {
            "DINING_SET": "комплекты на 4–6 персон",
            "TABLE": "столы в наличии",
            "CHAIRS": "стулья и кресла",
            "OUTDOOR_FURNITURE": "мебель для сада и террасы",
            "RATTAN_FURNITURE": "плетёную мебель и искусственный ротанг",
            "HORECA": "решения для HoReCa",
        }
        item = product_names.get(product, "релевантные товары в наличии")
        intent_messages = {
            "PRICE": "Покажите прозрачную стартовую цену и варианты комплектации.",
            "AVAILABILITY": "Сделайте акцент на наличии и возможности резервирования.",
            "DELIVERY": "Покажите сроки и понятные условия доставки.",
            "QUANTITY": "Предложите расчёт под количество и оптовые условия.",
        }
        return (
            f"Предложить {item} с конкретным наличием и понятным следующим шагом.",
            intent_messages.get(
                intent,
                "Покажите 3–5 подходящих вариантов и задайте один вопрос о задаче клиента.",
            ),
            f"Посадочная страница: {item}, наличие, цены, доставка и короткая форма консультации.",
        )

    async def competitors(self) -> list[dict]:
        async with self.session_factory() as session:
            competitors = (
                await session.scalars(
                    select(Competitor).order_by(Competitor.tier, Competitor.normalized_handle)
                )
            ).all()
            result = []
            for competitor in competitors:
                stats = await self._competitor_stats(session, competitor)
                won = int(
                    await session.scalar(
                        select(func.count(Deal.id))
                        .join(Lead, Lead.id == Deal.lead_id)
                        .where(
                            Lead.competitor_id == competitor.id,
                            Deal.status == DealStatus.WON,
                        )
                    )
                    or 0
                )
                snapshot_count = int(
                    await session.scalar(
                        select(func.count(DealSaleSnapshot.id))
                        .join(Deal, Deal.id == DealSaleSnapshot.deal_id)
                        .join(Lead, Lead.id == Deal.lead_id)
                        .where(
                            Lead.competitor_id == competitor.id,
                            Deal.status == DealStatus.WON,
                            DealSaleSnapshot.sale_currency == "UZS",
                        )
                    )
                    or 0
                )
                revenue = (
                    await session.scalar(
                        select(func.sum(DealSaleSnapshot.sale_amount))
                        .join(Deal, Deal.id == DealSaleSnapshot.deal_id)
                        .join(Lead, Lead.id == Deal.lead_id)
                        .where(
                            Lead.competitor_id == competitor.id,
                            Deal.status == DealStatus.WON,
                            DealSaleSnapshot.sale_currency == "UZS",
                        )
                    )
                    if snapshot_count == won
                    else None
                )
                if stats["comments"] < 10:
                    recommendation = "Набираем данные"
                    recommendation_tone = "muted"
                elif stats["commercial_rate"] >= 15 or won > 0:
                    recommendation = "Усилить мониторинг"
                    recommendation_tone = "good"
                elif stats["commercial_rate"] >= 5:
                    recommendation = "Оставить в работе"
                    recommendation_tone = "info"
                else:
                    recommendation = "Фоновый приоритет"
                    recommendation_tone = "warn"
                result.append(
                    {
                        "competitor": competitor,
                        **stats,
                        "won": won,
                        "revenue": revenue,
                        "recommendation": recommendation,
                        "recommendation_tone": recommendation_tone,
                    }
                )
            return result

    async def competitor_intelligence(self, competitor_id: int) -> dict | None:
        async with self.session_factory() as session:
            competitor = await session.get(Competitor, competitor_id)
            if competitor is None:
                return None
            stats = await self._competitor_stats(session, competitor)
            commercial_rows = (
                await session.execute(
                    select(Lead, Comment, Contact, Post)
                    .join(Comment, Comment.id == Lead.comment_id)
                    .join(Contact, Contact.id == Lead.contact_id)
                    .join(Post, Post.id == Comment.post_id)
                    .where(
                        Lead.competitor_id == competitor_id,
                        Lead.status != LeadStatus.NOT_LEAD,
                        Lead.lead_score >= 50,
                    )
                    .order_by(desc(Lead.lead_score), desc(Comment.discovered_at))
                )
            ).all()
            post_performance = []
            for post in stats["posts"]:
                rows = [row for row in commercial_rows if row[1].post_id == post.id]
                observed = int(
                    await session.scalar(
                        select(func.count(Comment.id)).where(Comment.post_id == post.id)
                    )
                    or 0
                )
                intents = Counter(lead.intent for lead, _comment, _contact, _post in rows)
                post_performance.append(
                    {
                        "post": post,
                        "observed_comments": observed,
                        "commercial_comments": len(rows),
                        "commercial_per_100": (
                            round(len(rows) / observed * 100, 1) if observed else 0.0
                        ),
                        "unique_buyers": len(
                            {contact.id for _lead, _comment, contact, _post in rows}
                        ),
                        "price": intents["PRICE"],
                        "availability": intents["AVAILABILITY"],
                        "delivery": intents["DELIVERY"],
                        "quantity": intents["QUANTITY"],
                    }
                )
            post_performance.sort(
                key=lambda item: (
                    item["commercial_comments"],
                    item["commercial_per_100"],
                ),
                reverse=True,
            )
            intent_counts = Counter(
                lead.intent for lead, _comment, _contact, _post in commercial_rows
            )
            product_counts = Counter(
                lead.product_category
                for lead, _comment, _contact, _post in commercial_rows
                if lead.product_category
            )
            opportunities = self._competitor_opportunities(intent_counts, product_counts)
            questions = [
                {
                    "lead": lead,
                    "comment": comment,
                    "contact": contact,
                    "post": post,
                }
                for lead, comment, contact, post in commercial_rows[:20]
            ]
            contact_ids = {contact.id for _lead, _comment, contact, _post in commercial_rows}
            overlaps = []
            if contact_ids:
                overlap_rows = (
                    await session.execute(
                        select(Competitor, func.count(func.distinct(Comment.contact_id)))
                        .join(Comment, Comment.competitor_id == Competitor.id)
                        .where(
                            Comment.contact_id.in_(contact_ids),
                            Competitor.id != competitor_id,
                        )
                        .group_by(Competitor.id)
                        .order_by(desc(func.count(func.distinct(Comment.contact_id))))
                    )
                ).all()
                overlaps = [{"competitor": item, "contacts": count} for item, count in overlap_rows]
            gap = await self.demand_gap_score(competitor_id)
            heatmap = await self.demand_heatmap(competitor_id=competitor_id, days=30)
            return {
                "competitor": competitor,
                **stats,
                "intent_counts": intent_counts.most_common(),
                "product_counts": product_counts.most_common(),
                "post_performance": post_performance,
                "opportunities": opportunities,
                "questions": questions,
                "overlaps": overlaps,
                "demand_gap": gap,
                "heatmap": heatmap,
                "public_response_observable": False,
            }

    async def competitor_overlap_network(self) -> list[dict]:
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(Comment.contact_id, Competitor.id, Competitor.normalized_handle)
                    .join(Competitor, Competitor.id == Comment.competitor_id)
                    .distinct()
                )
            ).all()
        by_contact: dict[int, set[tuple[int, str]]] = {}
        for contact_id, competitor_id, handle in rows:
            by_contact.setdefault(contact_id, set()).add((competitor_id, handle))
        pair_counts: Counter[tuple[tuple[int, str], tuple[int, str]]] = Counter()
        for companies in by_contact.values():
            for left, right in combinations(sorted(companies), 2):
                pair_counts[(left, right)] += 1
        return [
            {
                "left_id": left[0],
                "left": left[1],
                "right_id": right[0],
                "right": right[1],
                "contacts": count,
            }
            for (left, right), count in pair_counts.most_common(20)
        ]

    async def competitor_intelligence_overview(self) -> dict[str, int | float]:
        async with self.session_factory() as session:
            comments = int(await session.scalar(select(func.count(Comment.id))) or 0)
            commercial = int(
                await session.scalar(
                    select(func.count(Lead.id)).where(
                        Lead.status != LeadStatus.NOT_LEAD,
                        Lead.lead_score >= 50,
                    )
                )
                or 0
            )
            unique_buyers = int(
                await session.scalar(
                    select(func.count(func.distinct(Lead.contact_id))).where(
                        Lead.status != LeadStatus.NOT_LEAD,
                        Lead.lead_score >= 50,
                    )
                )
                or 0
            )
            source_counts = (
                select(
                    Comment.contact_id, func.count(func.distinct(Comment.competitor_id)).label("n")
                )
                .group_by(Comment.contact_id)
                .subquery()
            )
            multi = int(
                await session.scalar(
                    select(func.count()).select_from(source_counts).where(source_counts.c.n >= 2)
                )
                or 0
            )
        return {
            "observed_comments": comments,
            "commercial_comments": commercial,
            "commercial_rate": round(commercial / comments * 100, 1) if comments else 0.0,
            "unique_buyers": unique_buyers,
            "multi_competitor": multi,
        }

    async def demand_gap_score(self, competitor_id: int) -> dict:
        """Compute competitor demand gap analytics with strict row limits."""
        boundary_note = (
            "Мы не знаем, ответил ли конкурент клиенту через Direct или другой канал: "
            "данные ограничены сохранёнными публичными комментариями."
        )
        async with self.session_factory() as session:
            leads = (
                await session.scalars(
                    select(Lead)
                    .where(
                        Lead.competitor_id == competitor_id,
                        Lead.status != LeadStatus.NOT_LEAD,
                        Lead.lead_score >= 50,
                    )
                    .limit(500)
                )
            ).all()
            total_commercial = len(leads)
            if not total_commercial:
                return {
                    "competitor_id": competitor_id,
                    "total_commercial": 0,
                    "unworked_count": 0,
                    "unworked_rate": 0.0,
                    "b2b_gap": 0,
                    "multi_source_gap": 0,
                    "catalog_coverage_percent": None,
                    "catalog_coverage": [],
                    "boundary_note": boundary_note,
                }
            unworked = [
                lead
                for lead in leads
                if lead.status in (LeadStatus.NEW, LeadStatus.ANALYZING, LeadStatus.AI_PENDING)
            ]
            unworked_count = len(unworked)
            unworked_rate = round(unworked_count / total_commercial * 100, 1)

            b2b_roles = {"B2B_HORECA", "DESIGNER_CONTRACTOR"}
            b2b_gap = sum(
                1
                for lead in unworked
                if (lead.analysis_details or {}).get("buyer_role") in b2b_roles
                or lead.product_category in ("HORECA", "RATTAN_BAR_STOOL")
            )

            unworked_contact_ids = {lead.contact_id for lead in unworked}

            multi_source_gap = 0
            if unworked_contact_ids:
                source_counts = (
                    (
                        await session.execute(
                            select(Comment.contact_id)
                            .where(Comment.contact_id.in_(unworked_contact_ids))
                            .group_by(Comment.contact_id)
                            .having(func.count(func.distinct(Comment.competitor_id)) >= 2)
                        )
                    )
                    .scalars()
                    .all()
                )
                multi_source_gap = len(source_counts)

            demand_by_category: Counter[str] = Counter()
            evidence_by_category: dict[str, set[int]] = {}
            for lead in leads:
                category = normalize_product_category(lead.product_category)
                if category is None:
                    continue
                demand_by_category[category] += 1
                evidence_by_category.setdefault(category, set()).update(
                    int(item)
                    for item in (lead.analysis_details or {}).get("evidence_ids", [])
                    if isinstance(item, int)
                )
            product_rows = (
                await session.execute(
                    select(Product.category, func.count(Product.id))
                    .where(
                        Product.active.is_(True),
                        Product.category != "UNCONFIRMED",
                        Product.category_confirmed_at.is_not(None),
                    )
                    .group_by(Product.category)
                )
            ).all()
            products_by_category = {
                str(category): int(count) for category, count in product_rows
            }
            coverage = [
                {
                    "category": category,
                    "lead_count": lead_count,
                    "product_count": products_by_category.get(category, 0),
                    "covered": products_by_category.get(category, 0) > 0,
                    "evidence_ids": sorted(evidence_by_category.get(category, set()))[:10],
                }
                for category, lead_count in demand_by_category.most_common()
            ]
            covered_demand = sum(
                item["lead_count"] for item in coverage if item["covered"]
            )
            categorized_demand = sum(item["lead_count"] for item in coverage)
            catalog_coverage_percent = (
                round(covered_demand / categorized_demand * 100, 1)
                if products_by_category and categorized_demand
                else None
            )

            return {
                "competitor_id": competitor_id,
                "total_commercial": total_commercial,
                "unworked_count": unworked_count,
                "unworked_rate": unworked_rate,
                "b2b_gap": b2b_gap,
                "multi_source_gap": multi_source_gap,
                "catalog_coverage_percent": catalog_coverage_percent,
                "catalog_coverage": coverage,
                "boundary_note": boundary_note,
            }

    async def demand_gap_overview(self) -> list[dict]:
        """Summary demand gap table across all competitors."""
        async with self.session_factory() as session:
            competitors = (
                await session.scalars(select(Competitor).order_by(Competitor.normalized_handle))
            ).all()
            results = []
            for comp in competitors:
                gap = await self.demand_gap_score(comp.id)
                results.append(
                    {
                        "competitor": comp,
                        **gap,
                    }
                )
            results.sort(key=lambda x: (x["unworked_rate"], x["b2b_gap"]), reverse=True)
            return results

    async def demand_heatmap(self, competitor_id: int | None = None, days: int = 30) -> dict:
        """Temporal and product demand heatmap over the last N days."""
        now = datetime.now(UTC)
        cutoff = now - timedelta(days=days)
        async with self.session_factory() as session:
            stmt = (
                select(Lead, Comment.discovered_at)
                .join(Comment, Comment.id == Lead.comment_id)
                .where(
                    Lead.status != LeadStatus.NOT_LEAD,
                    Lead.lead_score >= 50,
                    Comment.discovered_at >= cutoff,
                )
            )
            if competitor_id is not None:
                stmt = stmt.where(Lead.competitor_id == competitor_id)
            stmt = stmt.limit(500)
            rows = (await session.execute(stmt)).all()

            by_product: Counter[str] = Counter()
            by_intent: Counter[str] = Counter()
            by_day: Counter[str] = Counter()

            for lead, discovered_at in rows:
                if lead.product_category:
                    by_product[lead.product_category] += 1
                if lead.intent:
                    by_intent[str(lead.intent)] += 1
                day_str = (
                    discovered_at.strftime("%Y-%m-%d")
                    if discovered_at
                    else now.strftime("%Y-%m-%d")
                )
                by_day[day_str] += 1

            days_series = []
            for i in range(days - 1, -1, -1):
                d_date = now - timedelta(days=i)
                d_str = d_date.strftime("%Y-%m-%d")
                days_series.append(
                    {
                        "date": d_str,
                        "label": d_date.strftime("%d.%m"),
                        "count": by_day.get(d_str, 0),
                    }
                )

            return {
                "total_signals": len(rows),
                "by_product": by_product.most_common(8),
                "by_intent": by_intent.most_common(8),
                "days_series": days_series,
                "days_count": days,
            }

    async def _competitor_stats(self, session: AsyncSession, competitor: Competitor) -> dict:
        posts = list(
            await session.scalars(
                select(Post)
                .where(Post.competitor_id == competitor.id)
                .order_by(desc(Post.published_at), desc(Post.id))
            )
        )
        comments = int(
            await session.scalar(
                select(func.count(Comment.id)).where(Comment.competitor_id == competitor.id)
            )
            or 0
        )
        leads = int(
            await session.scalar(
                select(func.count(Lead.id)).where(Lead.competitor_id == competitor.id)
            )
            or 0
        )
        commercial = int(
            await session.scalar(
                select(func.count(Lead.id)).where(
                    Lead.competitor_id == competitor.id,
                    Lead.status != LeadStatus.NOT_LEAD,
                    Lead.lead_score >= 50,
                )
            )
            or 0
        )
        hot = int(
            await session.scalar(
                select(func.count(Lead.id)).where(
                    Lead.competitor_id == competitor.id,
                    Lead.lead_score >= self.hot_threshold,
                    Lead.status != LeadStatus.NOT_LEAD,
                )
            )
            or 0
        )
        unique_buyers = int(
            await session.scalar(
                select(func.count(func.distinct(Lead.contact_id))).where(
                    Lead.competitor_id == competitor.id,
                    Lead.status != LeadStatus.NOT_LEAD,
                    Lead.lead_score >= 50,
                )
            )
            or 0
        )
        intent_rows = (
            await session.execute(
                select(Lead.intent, func.count(Lead.id))
                .where(
                    Lead.competitor_id == competitor.id,
                    Lead.status != LeadStatus.NOT_LEAD,
                    Lead.lead_score >= 50,
                )
                .group_by(Lead.intent)
            )
        ).all()
        intents = Counter({str(intent): int(count) for intent, count in intent_rows})
        contact_source_counts = (
            select(Comment.contact_id, func.count(func.distinct(Comment.competitor_id)).label("n"))
            .group_by(Comment.contact_id)
            .subquery()
        )
        multi_competitor = int(
            await session.scalar(
                select(func.count(func.distinct(Comment.contact_id)))
                .join(
                    contact_source_counts,
                    contact_source_counts.c.contact_id == Comment.contact_id,
                )
                .where(
                    Comment.competitor_id == competitor.id,
                    contact_source_counts.c.n >= 2,
                )
            )
            or 0
        )
        return {
            "posts": posts,
            "comments": comments,
            "leads": leads,
            "commercial": commercial,
            "commercial_rate": round(commercial / comments * 100, 1) if comments else 0.0,
            "hot": hot,
            "hot_rate": round(hot / comments * 100, 1) if comments else 0.0,
            "unique_buyers": unique_buyers,
            "multi_competitor": multi_competitor,
            "price_rate": round(intents["PRICE"] / comments * 100, 1) if comments else 0.0,
            "availability_rate": (
                round(intents["AVAILABILITY"] / comments * 100, 1) if comments else 0.0
            ),
            "delivery_rate": (round(intents["DELIVERY"] / comments * 100, 1) if comments else 0.0),
            "quantity_rate": (round(intents["QUANTITY"] / comments * 100, 1) if comments else 0.0),
        }

    @staticmethod
    def _competitor_opportunities(intents: Counter, products: Counter) -> list[dict[str, object]]:
        definitions = (
            (
                "PRICE",
                "Цена",
                "Показать стартовую цену или понятный диапазон в рекламе и карточке товара.",
            ),
            ("AVAILABILITY", "Наличие", "Продвигать позиции в наличии и добавить быстрый резерв."),
            ("DELIVERY", "Доставка", "Сделать сроки и стоимость доставки частью оффера."),
            (
                "QUANTITY",
                "Количество / B2B",
                "Подготовить расчёт под количество и оптовые условия.",
            ),
        )
        result = [
            {"intent": intent, "title": title, "signals": intents[intent], "action": action}
            for intent, title, action in definitions
            if intents[intent]
        ]
        if not result and products:
            product, count = products.most_common(1)[0]
            result.append(
                {
                    "intent": "PRODUCT",
                    "title": "Подтвердить товарный спрос",
                    "signals": count,
                    "action": f"Проверить оффер и наличие для категории {product}.",
                }
            )
        return result

    async def market_candidates(self) -> list[MarketCandidate]:
        async with self.session_factory() as session:
            return (
                await session.scalars(
                    select(MarketCandidate)
                    .where(MarketCandidate.status != "PROMOTED")
                    .order_by(
                        MarketCandidate.tier,
                        desc(MarketCandidate.confidence),
                        MarketCandidate.display_name,
                    )
                )
            ).all()

    async def market_overview(self) -> dict[str, int]:
        async with self.session_factory() as session:
            verified = int(await session.scalar(select(func.count(Competitor.id))) or 0)
            active = int(
                await session.scalar(
                    select(func.count(Competitor.id)).where(Competitor.active.is_(True))
                )
                or 0
            )
            candidates = int(
                await session.scalar(
                    select(func.count(MarketCandidate.id)).where(
                        MarketCandidate.status != "PROMOTED"
                    )
                )
                or 0
            )
            tier_a = int(
                await session.scalar(
                    select(func.count(Competitor.id)).where(Competitor.tier == "A")
                )
                or 0
            )
            return {
                "verified": verified,
                "active": active,
                "paused": max(0, verified - active),
                "candidates": candidates,
                "tier_a": tier_a,
            }

    async def tasks(self, *, view: str = "open", q: str = "", limit: int = 300) -> list:
        now = datetime.now(UTC)
        async with self.session_factory() as session:
            stmt = (
                select(ContactTask, Contact, Lead)
                .join(Contact, Contact.id == ContactTask.contact_id)
                .outerjoin(Lead, Lead.id == ContactTask.lead_id)
                .order_by(ContactTask.status, ContactTask.due_at)
                .limit(limit)
            )
            normalized = view.strip().lower()
            if normalized == "overdue":
                stmt = stmt.where(ContactTask.status == TaskStatus.OPEN, ContactTask.due_at < now)
            elif normalized == "today":
                stmt = stmt.where(
                    ContactTask.status == TaskStatus.OPEN,
                    ContactTask.due_at >= now,
                    ContactTask.due_at <= now + timedelta(hours=24),
                )
            elif normalized == "done":
                stmt = stmt.where(ContactTask.status == TaskStatus.DONE)
            else:
                stmt = stmt.where(ContactTask.status == TaskStatus.OPEN)
            if q.strip():
                pattern = f"%{q.strip().lower()}%"
                stmt = stmt.where(
                    or_(
                        func.lower(Contact.username).like(pattern),
                        func.lower(func.coalesce(Contact.display_name, "")).like(pattern),
                        func.lower(ContactTask.note).like(pattern),
                    )
                )
            return (await session.execute(stmt)).all()

    async def deals(self, *, status: str = "", q: str = "", limit: int = 300) -> list:
        async with self.session_factory() as session:
            stmt = (
                select(Deal, Lead, Contact, Competitor)
                .join(Lead, Lead.id == Deal.lead_id)
                .join(Contact, Contact.id == Deal.contact_id)
                .join(Competitor, Competitor.id == Lead.competitor_id)
                .order_by(desc(Deal.updated_at), desc(Deal.created_at))
                .limit(limit)
            )
            if status.strip():
                try:
                    stmt = stmt.where(Deal.status == DealStatus(status.strip().upper()))
                except ValueError:
                    return []
            if q.strip():
                pattern = f"%{q.strip().lower()}%"
                stmt = stmt.where(
                    or_(
                        func.lower(Contact.username).like(pattern),
                        func.lower(func.coalesce(Deal.product_name, "")).like(pattern),
                        func.lower(Competitor.normalized_handle).like(pattern),
                    )
                )
            return (await session.execute(stmt)).all()

    async def economics(self, days: int = 30) -> dict:
        page = await EconomicsPageService(
            self.session_factory,
            self.hot_threshold,
        ).snapshot(days)
        return {"page": page, "economics": page.usd}

    async def analytics(self, days: int = 30) -> dict:
        started_at = datetime.now(UTC) - timedelta(days=days)
        async with self.session_factory() as session:
            funnel_rows = (
                await session.execute(
                    select(Lead.status, func.count(Lead.id))
                    .where(Lead.created_at >= started_at)
                    .group_by(Lead.status)
                )
            ).all()
            intent_rows = (
                await session.execute(
                    select(Lead.intent, func.count(Lead.id))
                    .where(Lead.status != LeadStatus.NOT_LEAD, Lead.created_at >= started_at)
                    .group_by(Lead.intent)
                    .order_by(desc(func.count(Lead.id)))
                )
            ).all()
            product_rows = (
                await session.execute(
                    select(Lead.product_category, func.count(Lead.id))
                    .where(
                        Lead.product_category.is_not(None),
                        Lead.status != LeadStatus.NOT_LEAD,
                        Lead.created_at >= started_at,
                    )
                    .group_by(Lead.product_category)
                    .order_by(desc(func.count(Lead.id)))
                )
            ).all()
            lost_rows = (
                await session.execute(
                    select(Deal.lost_reason, func.count(Deal.id))
                    .where(
                        Deal.status == DealStatus.LOST,
                        Deal.lost_reason.is_not(None),
                        func.coalesce(Deal.lost_at, Deal.updated_at) >= started_at,
                    )
                    .group_by(Deal.lost_reason)
                    .order_by(desc(func.count(Deal.id)))
                )
            ).all()
            feedback_total = int(
                await session.scalar(
                    select(func.count(AIFeedback.id)).where(AIFeedback.created_at >= started_at)
                )
                or 0
            )
            feedback_sales = int(
                await session.scalar(
                    select(func.count(AIFeedback.id)).where(
                        AIFeedback.deal_won.is_(True),
                        AIFeedback.created_at >= started_at,
                    )
                )
                or 0
            )
        return {
            "days": days,
            "funnel": {getattr(key, "value", str(key)): value for key, value in funnel_rows},
            "intents": intent_rows,
            "products": product_rows,
            "lost_reasons": lost_rows,
            "feedback_total": feedback_total,
            "feedback_sales": feedback_sales,
        }

    async def monitor_runs(self, limit: int = 80) -> list[MonitorRun]:
        async with self.session_factory() as session:
            return (
                await session.scalars(
                    select(MonitorRun).order_by(desc(MonitorRun.started_at)).limit(limit)
                )
            ).all()

    async def usage_today(self) -> dict[str, int]:
        now = datetime.now(UTC)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(ExternalUsage.service, func.coalesce(func.sum(ExternalUsage.units), 0))
                    .where(ExternalUsage.created_at >= start)
                    .group_by(ExternalUsage.service)
                )
            ).all()
        return {service: int(units or 0) for service, units in rows}

    async def scan_plan(
        self,
        *,
        max_units_per_scan: int,
        daily_remaining: int,
        live_enabled: bool,
    ) -> dict[str, int | bool]:
        """Build a zero-cost estimate from data already stored in our DB.

        It deliberately does not call Instagram. The estimate is conservative enough for a human
        to understand what a manual live scan is likely to do, while the provider-level scan budget
        remains the hard enforcement mechanism.
        """
        async with self.session_factory() as session:
            active_competitors = int(
                await session.scalar(
                    select(func.count(Competitor.id)).where(Competitor.active.is_(True))
                )
                or 0
            )
            due_competitors = int(
                await session.scalar(
                    select(func.count(Competitor.id)).where(
                        Competitor.active.is_(True),
                        or_(
                            Competitor.next_scan_at.is_(None),
                            Competitor.next_scan_at <= datetime.now(UTC),
                        ),
                    )
                )
                or 0
            )
            comment_candidates = int(
                await session.scalar(
                    select(func.count(Post.id))
                    .join(Competitor, Competitor.id == Post.competitor_id)
                    .where(
                        Competitor.active.is_(True),
                        Post.comments_count > 0,
                        or_(
                            Post.last_synced_remote_count.is_(None),
                            Post.last_synced_remote_count != Post.comments_count,
                        ),
                    )
                )
                or 0
            )
            partial_posts = int(
                await session.scalar(
                    select(func.count(Post.id))
                    .join(Competitor, Competitor.id == Post.competitor_id)
                    .where(
                        Competitor.active.is_(True),
                        Post.coverage_status.in_(["PARTIAL", "LATEST_ONLY", "UNKNOWN"]),
                    )
                )
                or 0
            )

        hard_cap = max(0, min(max_units_per_scan, daily_remaining)) if live_enabled else 0
        # One get_reels per active competitor + usually one comments page per changed Reel. Fallback
        # and pagination can make the real number higher, but never above hard_cap.
        expected_min = active_competitors + comment_candidates if live_enabled else 0
        return {
            "live_enabled": live_enabled,
            "active_competitors": active_competitors,
            "due_competitors": due_competitors,
            "comment_candidates": comment_candidates,
            "partial_posts": partial_posts,
            "expected_min_units": min(expected_min, hard_cap) if hard_cap else 0,
            "hard_cap_units": hard_cap,
            "daily_remaining": max(0, daily_remaining),
        }

    @staticmethod
    async def _count(session: AsyncSession, model: type) -> int:
        return int(await session.scalar(select(func.count(model.id))) or 0)
