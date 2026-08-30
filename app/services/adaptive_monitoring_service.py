from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Comment, Competitor, Lead, Post
from app.db.repositories.competitors import CompetitorRepository
from app.services.adaptive_monitoring_policy import (
    AdaptiveMonitoringPolicy,
    CompetitorMonitoringFacts,
    MonitoringDecision,
)


@dataclass(frozen=True, slots=True)
class CompetitorScanPlan:
    competitor_id: int
    handle: str
    state: str
    priority_score: int
    next_due_at: datetime


class AdaptiveMonitoringService:
    """Пересчитывает state/due/priority только из сохранённых наблюдаемых фактов."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        hot_threshold: int,
    ) -> None:
        self.session_factory = session_factory
        self.hot_threshold = hot_threshold

    async def ranked_due_competitors(
        self,
        configured_handles: list[str],
        *,
        force: bool,
    ) -> tuple[list[CompetitorScanPlan], int]:
        now = datetime.now(UTC)
        async with self.session_factory() as session:
            repo = CompetitorRepository(session)
            for handle in configured_handles:
                await repo.get_or_create(handle)
            await session.flush()
            competitors = list(
                await session.scalars(
                    select(Competitor).where(Competitor.active.is_(True))
                )
            )
            decisions = await self._decisions(session, competitors, now)
            plans: list[CompetitorScanPlan] = []
            not_due = 0
            for competitor in competitors:
                decision = decisions[competitor.id]
                self._apply(competitor, decision)
                due = (
                    force
                    or competitor.last_scanned_at is None
                    or decision.next_due_at <= now
                )
                if due:
                    plans.append(
                        CompetitorScanPlan(
                            competitor_id=competitor.id,
                            handle=competitor.normalized_handle,
                            state=decision.state,
                            priority_score=decision.priority_score,
                            next_due_at=decision.next_due_at,
                        )
                    )
                else:
                    not_due += 1
            await session.commit()
        plans.sort(key=lambda item: (-item.priority_score, item.next_due_at, item.handle))
        return plans, not_due

    async def mark_scanned(self, handle: str, *, success: bool) -> None:
        now = datetime.now(UTC)
        async with self.session_factory() as session:
            competitor = await CompetitorRepository(session).get_or_create(handle)
            competitor.last_scanned_at = now
            competitor.scan_error_count = (
                0 if success else competitor.scan_error_count + 1
            )
            await session.flush()
            decision = (
                await self._decisions(session, [competitor], now)
            )[competitor.id]
            self._apply(competitor, decision)
            await session.commit()

    async def _decisions(
        self,
        session: AsyncSession,
        competitors: list[Competitor],
        now: datetime,
    ) -> dict[int, MonitoringDecision]:
        if not competitors:
            return {}
        ids = [item.id for item in competitors]
        newest_reels = {
            competitor_id: observed_at
            for competitor_id, observed_at in (
                await session.execute(
                    select(
                        Post.competitor_id,
                        func.max(func.coalesce(Post.published_at, Post.created_at)),
                    )
                    .where(Post.competitor_id.in_(ids))
                    .group_by(Post.competitor_id)
                )
            ).all()
        }
        cutoff = now - timedelta(days=30)
        lead_rows = (
            await session.execute(
                select(Lead, Comment)
                .join(Comment, Comment.id == Lead.comment_id)
                .where(
                    Lead.competitor_id.in_(ids),
                    Comment.discovered_at >= cutoff,
                )
            )
        ).all()
        commercial_dates: dict[int, list[datetime]] = {}
        hot_dates: dict[int, list[datetime]] = {}
        b2b_dates: dict[int, list[datetime]] = {}
        for lead, comment in lead_rows:
            details = lead.analysis_details or {}
            if details.get("is_commercial") is not True:
                continue
            observed_at = self._aware(comment.discovered_at)
            commercial_dates.setdefault(lead.competitor_id, []).append(observed_at)
            if lead.lead_score >= self.hot_threshold:
                hot_dates.setdefault(lead.competitor_id, []).append(observed_at)
            if details.get("buyer_role") == "B2B_HORECA":
                b2b_dates.setdefault(lead.competitor_id, []).append(observed_at)

        decisions: dict[int, MonitoringDecision] = {}
        for competitor in competitors:
            commercial = commercial_dates.get(competitor.id, [])
            hot = hot_dates.get(competitor.id, [])
            b2b = b2b_dates.get(competitor.id, [])
            decisions[competitor.id] = AdaptiveMonitoringPolicy.decide(
                CompetitorMonitoringFacts(
                    competitor_id=competitor.id,
                    handle=competitor.normalized_handle,
                    tier=competitor.tier,
                    last_scanned_at=competitor.last_scanned_at,
                    newest_reel_at=newest_reels.get(competitor.id),
                    last_commercial_at=max(commercial, default=None),
                    last_hot_at=max(hot, default=None),
                    last_b2b_at=max(b2b, default=None),
                    commercial_signals_30d=len(commercial),
                    scan_error_count=competitor.scan_error_count,
                ),
                now=now,
            )
        return decisions

    @staticmethod
    def _apply(competitor: Competitor, decision: MonitoringDecision) -> None:
        competitor.monitoring_state = decision.state
        competitor.next_scan_at = decision.next_due_at
        competitor.adaptive_priority_score = decision.priority_score
        competitor.adaptive_reasons_json = list(decision.reasons)
        competitor.adaptive_policy_version = AdaptiveMonitoringPolicy.VERSION

    @staticmethod
    def _aware(value: datetime) -> datetime:
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
