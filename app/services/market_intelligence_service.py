from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import normalize_instagram_handle
from app.data.competitor_catalog import MARKET_CANDIDATES, MONITORED_COMPETITORS
from app.db.models import Competitor, MarketCandidate, Vertical


class MarketIntelligenceService:
    """Keeps the product's market map in the database.

    Catalog sync is intentionally idempotent and cost-free: it only touches our own database.
    New monitored competitors are inserted paused unless the seed explicitly opts in, so expanding
    the market map cannot silently increase paid provider traffic.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def sync_catalog(self) -> dict[str, int]:
        created_competitors = 0
        created_candidates = 0
        promoted_candidates = 0
        monitored_names = {seed.display_name.casefold() for seed in MONITORED_COMPETITORS}
        monitored_handles = {
            normalize_instagram_handle(seed.handle) for seed in MONITORED_COMPETITORS
        }
        async with self.session_factory() as session:
            for seed in MONITORED_COMPETITORS:
                handle = normalize_instagram_handle(seed.handle)
                row = await session.scalar(
                    select(Competitor).where(Competitor.normalized_handle == handle)
                )
                if row is None:
                    row = Competitor(
                        handle=handle,
                        normalized_handle=handle,
                        display_name=seed.display_name,
                        category=seed.category,
                        tier=seed.tier,
                        poll_interval_seconds={"A": 180, "B": 600, "C": 1800}[seed.tier],
                        active=seed.active_by_default,
                        notes=seed.notes,
                        website_url=seed.website_url or None,
                        catalog_managed=True,
                    )
                    session.add(row)
                    created_competitors += 1
                else:
                    # Never override the user's live/pause choice or their tier after first import.
                    row.display_name = row.display_name or seed.display_name
                    row.notes = row.notes or seed.notes
                    row.website_url = row.website_url or seed.website_url or None
                    row.catalog_managed = True

            for seed in MARKET_CANDIDATES:
                candidate_handle = (
                    normalize_instagram_handle(seed.instagram_handle)
                    if seed.instagram_handle
                    else None
                )
                is_monitored = (
                    seed.display_name.casefold() in monitored_names
                    or candidate_handle in monitored_handles
                )
                row = await session.scalar(
                    select(MarketCandidate).where(MarketCandidate.display_name == seed.display_name)
                )
                if row is None:
                    row = MarketCandidate(
                        display_name=seed.display_name,
                        vertical=Vertical(seed.vertical),
                        contact_hint=seed.contact_hint or None,
                        instagram_handle=candidate_handle,
                        website_url=seed.website_url or None,
                        category=seed.category,
                        tier=seed.tier,
                        confidence=seed.confidence,
                        rationale=seed.rationale,
                        status="PROMOTED" if is_monitored else seed.status,
                    )
                    session.add(row)
                    created_candidates += 1
                else:
                    row.instagram_handle = row.instagram_handle or (
                        candidate_handle
                    )
                    row.website_url = row.website_url or seed.website_url or None
                    row.rationale = row.rationale or seed.rationale
                    row.contact_hint = row.contact_hint or seed.contact_hint or None
                    row.confidence = max(row.confidence, seed.confidence)
                    if is_monitored and row.status != "PROMOTED":
                        row.status = "PROMOTED"
                        promoted_candidates += 1
            await session.commit()
        return {
            "created_competitors": created_competitors,
            "created_candidates": created_candidates,
            "promoted_candidates": promoted_candidates,
        }

    async def promote_candidate(
        self,
        candidate_id: int,
        *,
        handle: str,
        active: bool = False,
    ) -> Competitor:
        normalized = normalize_instagram_handle(handle)
        if not normalized:
            raise ValueError("Укажите Instagram username")
        async with self.session_factory() as session:
            candidate = await session.get(MarketCandidate, candidate_id)
            if candidate is None:
                raise ValueError("Кандидат не найден")
            competitor = await session.scalar(
                select(Competitor).where(Competitor.normalized_handle == normalized)
            )
            if competitor is None:
                competitor = Competitor(
                    handle=normalized,
                    normalized_handle=normalized,
                    display_name=candidate.display_name,
                    category=candidate.category,
                    tier=candidate.tier,
                    poll_interval_seconds={"A": 180, "B": 600, "C": 1800}[candidate.tier],
                    active=active,
                    notes=candidate.rationale,
                    website_url=candidate.website_url,
                    catalog_managed=True,
                )
                session.add(competitor)
            candidate.instagram_handle = normalized
            candidate.status = "PROMOTED"
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                competitor = await session.scalar(
                    select(Competitor).where(
                        Competitor.normalized_handle == normalized
                    )
                )
                candidate = await session.get(MarketCandidate, candidate_id)
                if competitor is None or candidate is None:
                    raise
                candidate.instagram_handle = normalized
                candidate.status = "PROMOTED"
                await session.commit()
            return competitor
