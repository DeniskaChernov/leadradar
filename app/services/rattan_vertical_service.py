"""Rattan as a separate source portfolio, not auto-tagged furniture scan."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import (
    BusinessEntity,
    Comment,
    Competitor,
    Evidence,
    Lead,
    Post,
    PublicSignal,
    Vertical,
)
from app.services.rattan_taxonomy_service import RattanTaxonomyService


def sync_business_vertical_enrollment(
    business: BusinessEntity | None,
    *,
    vertical: Vertical,
) -> None:
    """Sync BusinessEntity.verticals_json with source portfolio enrollment."""
    if business is None:
        return
    current = set(business.verticals_json or [])
    if vertical == Vertical.ARTIFICIAL_RATTAN:
        current.add(Vertical.ARTIFICIAL_RATTAN.value)
    else:
        current.discard(Vertical.ARTIFICIAL_RATTAN.value)
    business.verticals_json = sorted(current)


@dataclass(frozen=True, slots=True)
class RattanRebuildStats:
    signals_checked: int
    rattan_signals: int
    raw_material_signals: int
    ready_furniture_signals: int
    unclassified_rattan_signals: int
    enrolled_competitors: int
    orphan_rattan_signals: int


class RattanVerticalService:
    """Taxonomy labels evidence; portfolio vertical = Competitor.vertical only."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def rebuild(self) -> RattanRebuildStats:
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(PublicSignal, Comment, Post, Evidence, Lead, Competitor)
                    .join(Comment, Comment.id == PublicSignal.comment_id)
                    .join(Post, Post.id == Comment.post_id)
                    .join(Evidence, Evidence.public_signal_id == PublicSignal.id)
                    .join(Competitor, Competitor.id == PublicSignal.competitor_id)
                    .outerjoin(Lead, Lead.comment_id == Comment.id)
                    .order_by(PublicSignal.id, Evidence.id)
                )
            ).all()
            layers = {"RAW_MATERIAL": 0, "READY_FURNITURE": 0, "NONE": 0}
            seen_signals: set[int] = set()
            orphan_ids: set[int] = set()
            for signal, comment, post, evidence, lead, competitor in rows:
                taxonomy = RattanTaxonomyService.classify(
                    f"{post.caption}\n{comment.text}"
                )
                payload = {
                    "version": RattanTaxonomyService.VERSION,
                    "layer": taxonomy.layer.value,
                    "role": taxonomy.role.value,
                    "products": list(taxonomy.products),
                    "material_profiles": list(taxonomy.material_profiles),
                    "evidence": list(taxonomy.evidence),
                    "negative_evidence": list(taxonomy.negative_evidence),
                    "taxonomy_vertical": taxonomy.vertical.value,
                }
                # Портфель строго по источнику — taxonomy не переносит мебель в ротанг.
                portfolio_vertical = competitor.vertical
                signal.vertical = portfolio_vertical
                evidence.vertical = portfolio_vertical
                evidence.topic = taxonomy.products[0] if taxonomy.products else None
                evidence.intent = (
                    taxonomy.layer.value
                    if taxonomy.is_rattan and taxonomy.layer.value != "NONE"
                    else None
                )
                evidence.strength = taxonomy.confidence if taxonomy.is_rattan else 0
                evidence.raw_data = {**(evidence.raw_data or {}), "rattan_taxonomy": payload}
                if lead is not None:
                    lead.vertical = portfolio_vertical
                    details = dict(lead.analysis_details or {})
                    details["vertical"] = portfolio_vertical.value
                    details["rattan_taxonomy"] = payload
                    lead.analysis_details = details
                    if (
                        portfolio_vertical == Vertical.ARTIFICIAL_RATTAN
                        and taxonomy.layer.value == "RAW_MATERIAL"
                        and taxonomy.products
                    ):
                        lead.product_category = taxonomy.products[0]
                if taxonomy.is_rattan:
                    if signal.id not in seen_signals:
                        layers[taxonomy.layer.value] += 1
                    if competitor.vertical != Vertical.ARTIFICIAL_RATTAN:
                        orphan_ids.add(signal.id)
                seen_signals.add(signal.id)

            enrolled_count = int(
                await session.scalar(
                    select(func.count(Competitor.id)).where(
                        Competitor.vertical == Vertical.ARTIFICIAL_RATTAN
                    )
                )
                or 0
            )
            await session.commit()
            return RattanRebuildStats(
                signals_checked=len(seen_signals),
                rattan_signals=sum(layers.values()),
                raw_material_signals=layers["RAW_MATERIAL"],
                ready_furniture_signals=layers["READY_FURNITURE"],
                unclassified_rattan_signals=layers["NONE"],
                enrolled_competitors=enrolled_count,
                orphan_rattan_signals=len(orphan_ids),
            )

    async def enroll_competitor(
        self,
        competitor_id: int,
        *,
        vertical: Vertical,
    ) -> Competitor:
        """Explicitly enroll a source into furniture or rattan portfolio."""
        if vertical not in {Vertical.FURNITURE, Vertical.ARTIFICIAL_RATTAN}:
            raise ValueError("Вертикаль должна быть FURNITURE или ARTIFICIAL_RATTAN")
        async with self.session_factory() as session:
            competitor = await session.get(Competitor, competitor_id)
            if competitor is None:
                raise ValueError("Конкурент не найден")
            competitor.vertical = vertical
            if competitor.business_id:
                business = await session.get(BusinessEntity, competitor.business_id)
                sync_business_vertical_enrollment(business, vertical=vertical)
            # Синхронизируем уже собранные signal/lead с портфелем источника.
            signals = list(
                await session.scalars(
                    select(PublicSignal).where(PublicSignal.competitor_id == competitor_id)
                )
            )
            for signal in signals:
                signal.vertical = vertical
            leads = list(
                await session.scalars(select(Lead).where(Lead.competitor_id == competitor_id))
            )
            for lead in leads:
                lead.vertical = vertical
                details = dict(lead.analysis_details or {})
                details["vertical"] = vertical.value
                lead.analysis_details = details
            evidence_rows = list(
                await session.scalars(
                    select(Evidence).where(
                        Evidence.public_signal_id.in_([item.id for item in signals] or [-1])
                    )
                )
            )
            for evidence in evidence_rows:
                evidence.vertical = vertical
            await session.commit()
            await session.refresh(competitor)
            return competitor
