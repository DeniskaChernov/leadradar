"""Классификация свежести конкурента по последней публикации (без paid scan)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import normalize_instagram_handle
from app.db.models import Competitor, Post

FRESHNESS_ACTIVE = "ACTIVE"
FRESHNESS_STALE = "STALE"
FRESHNESS_DORMANT = "DORMANT"
FRESHNESS_INACTIVE = "INACTIVE"
FRESHNESS_UNKNOWN = "UNKNOWN"

_ACTIVE_DAYS = 30
_STALE_DAYS = 90
_DORMANT_DAYS = 180


@dataclass(frozen=True, slots=True)
class FreshnessDecision:
    status: str
    reason: str
    latest_publication_at: datetime | None


class CompetitorFreshnessService:
    """Durable freshness boundary: ACTIVE/STALE/DORMANT/INACTIVE/UNKNOWN."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    @staticmethod
    def classify(
        latest_publication_at: datetime | None,
        *,
        now: datetime | None = None,
    ) -> FreshnessDecision:
        reference = now or datetime.now(UTC)
        if reference.tzinfo is None:
            reference = reference.replace(tzinfo=UTC)
        if latest_publication_at is None:
            return FreshnessDecision(
                status=FRESHNESS_UNKNOWN,
                reason="Нет известной даты публикации",
                latest_publication_at=None,
            )
        observed = latest_publication_at
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=UTC)
        age = reference - observed.astimezone(UTC)
        if age <= timedelta(days=_ACTIVE_DAYS):
            return FreshnessDecision(
                status=FRESHNESS_ACTIVE,
                reason=f"Публикация не старше {_ACTIVE_DAYS} дней",
                latest_publication_at=observed,
            )
        if age <= timedelta(days=_STALE_DAYS):
            return FreshnessDecision(
                status=FRESHNESS_STALE,
                reason=f"Публикация {_ACTIVE_DAYS + 1}–{_STALE_DAYS} дней назад",
                latest_publication_at=observed,
            )
        if age <= timedelta(days=_DORMANT_DAYS):
            return FreshnessDecision(
                status=FRESHNESS_DORMANT,
                reason=f"Публикация {_STALE_DAYS + 1}–{_DORMANT_DAYS} дней назад",
                latest_publication_at=observed,
            )
        return FreshnessDecision(
            status=FRESHNESS_INACTIVE,
            reason=f"Публикация старше {_DORMANT_DAYS} дней",
            latest_publication_at=observed,
        )

    @staticmethod
    def is_pilot_approved(competitor: Competitor, *, now: datetime | None = None) -> bool:
        """ACTIVE или ручное подтверждение оператора для первого pilot."""
        status = (competitor.freshness_status or FRESHNESS_UNKNOWN).upper()
        if status == FRESHNESS_ACTIVE:
            return True
        confirmed = competitor.manual_freshness_confirmed_at
        if confirmed is None:
            return False
        reference = now or datetime.now(UTC)
        if confirmed.tzinfo is None:
            confirmed = confirmed.replace(tzinfo=UTC)
        if reference.tzinfo is None:
            reference = reference.replace(tzinfo=UTC)
        return confirmed <= reference

    async def refresh_competitor(self, competitor_id: int) -> Competitor:
        async with self.session_factory() as session:
            competitor = await session.get(Competitor, competitor_id)
            if competitor is None:
                raise ValueError(f"Competitor id={competitor_id} not found")
            latest = await session.scalar(
                select(func.max(func.coalesce(Post.published_at, Post.created_at))).where(
                    Post.competitor_id == competitor_id
                )
            )
            decision = self.classify(latest)
            competitor.latest_publication_at = decision.latest_publication_at
            competitor.freshness_status = decision.status
            competitor.freshness_reason = decision.reason
            competitor.freshness_checked_at = datetime.now(UTC)
            await session.commit()
            await session.refresh(competitor)
            return competitor

    async def refresh_handle(self, handle: str) -> Competitor:
        normalized = normalize_instagram_handle(handle)
        async with self.session_factory() as session:
            competitor = await session.scalar(
                select(Competitor).where(Competitor.normalized_handle == normalized)
            )
            if competitor is None:
                raise ValueError(f"Competitor @{normalized} not found")
            competitor_id = competitor.id
        return await self.refresh_competitor(competitor_id)

    async def confirm_for_pilot(self, handle: str, *, manager_id: int | None = None) -> Competitor:
        """Операторское подтверждение без paid scan (не удаляет историю)."""
        normalized = normalize_instagram_handle(handle)
        now = datetime.now(UTC)
        async with self.session_factory() as session:
            competitor = await session.scalar(
                select(Competitor).where(Competitor.normalized_handle == normalized)
            )
            if competitor is None:
                raise ValueError(f"Competitor @{normalized} not found")
            latest = await session.scalar(
                select(func.max(func.coalesce(Post.published_at, Post.created_at))).where(
                    Post.competitor_id == competitor.id
                )
            )
            decision = self.classify(latest, now=now)
            competitor.latest_publication_at = decision.latest_publication_at
            competitor.freshness_status = decision.status
            competitor.freshness_reason = (
                f"{decision.reason}; manual confirm by manager={manager_id or 'unknown'}"
            )
            competitor.freshness_checked_at = now
            competitor.manual_freshness_confirmed_at = now
            await session.commit()
            await session.refresh(competitor)
            return competitor
