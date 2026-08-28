from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
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


@dataclass(frozen=True, slots=True)
class RattanRebuildStats:
    signals_checked: int
    rattan_signals: int
    raw_material_signals: int
    ready_furniture_signals: int
    unclassified_rattan_signals: int
    competitors: int


class RattanVerticalService:
    """Idempotently propagate strict taxonomy through already persisted records."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def rebuild(self) -> RattanRebuildStats:
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(PublicSignal, Comment, Post, Evidence, Lead)
                    .join(Comment, Comment.id == PublicSignal.comment_id)
                    .join(Post, Post.id == Comment.post_id)
                    .join(Evidence, Evidence.public_signal_id == PublicSignal.id)
                    .outerjoin(Lead, Lead.comment_id == Comment.id)
                    .order_by(PublicSignal.id, Evidence.id)
                )
            ).all()
            rattan_competitor_ids: set[int] = set()
            layers = {"RAW_MATERIAL": 0, "READY_FURNITURE": 0, "NONE": 0}
            seen_signals: set[int] = set()
            for signal, comment, post, evidence, lead in rows:
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
                }
                signal.vertical = taxonomy.vertical
                evidence.vertical = taxonomy.vertical
                evidence.topic = taxonomy.products[0] if taxonomy.products else None
                evidence.intent = (
                    taxonomy.layer.value
                    if taxonomy.is_rattan and taxonomy.layer.value != "NONE"
                    else None
                )
                evidence.strength = taxonomy.confidence if taxonomy.is_rattan else 0
                evidence.raw_data = {**(evidence.raw_data or {}), "rattan_taxonomy": payload}
                if lead is not None:
                    lead.vertical = taxonomy.vertical
                    details = dict(lead.analysis_details or {})
                    details["vertical"] = taxonomy.vertical.value
                    details["rattan_taxonomy"] = payload
                    lead.analysis_details = details
                    if taxonomy.layer.value == "RAW_MATERIAL" and taxonomy.products:
                        lead.product_category = taxonomy.products[0]
                if taxonomy.is_rattan:
                    rattan_competitor_ids.add(signal.competitor_id)
                    if signal.id not in seen_signals:
                        layers[taxonomy.layer.value] += 1
                seen_signals.add(signal.id)

            competitors = list(await session.scalars(select(Competitor)))
            for competitor in competitors:
                if competitor.id in rattan_competitor_ids:
                    competitor.vertical = Vertical.ARTIFICIAL_RATTAN
                    if competitor.business_id:
                        business = await session.get(BusinessEntity, competitor.business_id)
                        if business is not None:
                            business.verticals_json = sorted(
                                set(business.verticals_json or []).union(
                                    {Vertical.ARTIFICIAL_RATTAN.value}
                                )
                            )
            await session.commit()
            return RattanRebuildStats(
                signals_checked=len(seen_signals),
                rattan_signals=sum(layers.values()),
                raw_material_signals=layers["RAW_MATERIAL"],
                ready_furniture_signals=layers["READY_FURNITURE"],
                unclassified_rattan_signals=layers["NONE"],
                competitors=len(rattan_competitor_ids),
            )
