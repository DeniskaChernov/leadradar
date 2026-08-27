from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import prod
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import (
    AudienceMembership,
    AudienceSegment,
    Comment,
    Contact,
    ContactIntelligence,
    ContactInterestProfile,
    Deal,
    DealStatus,
    Evidence,
    ExportEligibility,
    InterestEvidence,
    Lead,
    LeadStatus,
    OutcomeDNA,
    PublicSignal,
)
from app.services.b2b_policy import B2BPolicy

# ---------------------------------------------------------------------------
# Segment registry
# ---------------------------------------------------------------------------

_BUYER_ROLE_PRIORITY = {
    "B2B_HORECA": 4,
    "DESIGNER_CONTRACTOR": 3,
    "B2C_CONSUMER": 2,
    "JOB_SEEKER": 1,
    "UNKNOWN": 0,
}


@dataclass(frozen=True, slots=True)
class SegmentDefinition:
    slug: str
    name: str
    description: str
    criteria: dict[str, object]


SEGMENTS = (
    SegmentDefinition(
        "hot-24h",
        "Горячие покупатели · 24 часа",
        "HOT-сигналы за последние сутки.",
        {"hot": True, "days": 1},
    ),
    SegmentDefinition(
        "hot-7d",
        "Горячие покупатели · 7 дней",
        "HOT-сигналы за последние 7 дней.",
        {"hot": True, "days": 7},
    ),
    SegmentDefinition(
        "hot-30d",
        "Горячие покупатели · 30 дней",
        "HOT-сигналы за последние 30 дней.",
        {"hot": True, "days": 30},
    ),
    SegmentDefinition(
        "dining-sets",
        "Обеденные комплекты",
        "Наблюдаемый интерес к обеденным комплектам.",
        {"product": "DINING_SET"},
    ),
    SegmentDefinition("tables", "Столы", "Наблюдаемый интерес к столам.", {"product": "TABLE"}),
    SegmentDefinition(
        "chairs",
        "Стулья и кресла",
        "Наблюдаемый интерес к стульям и креслам.",
        {"product": "CHAIRS"},
    ),
    SegmentDefinition(
        "outdoor",
        "Outdoor",
        "Наблюдаемый спрос на садовую и террасную мебель.",
        {"product": "OUTDOOR_FURNITURE"},
    ),
    SegmentDefinition(
        "rattan",
        "Плетёная мебель",
        "Наблюдаемый интерес к плетёной мебели и ротангу.",
        {"product": "RATTAN_FURNITURE"},
    ),
    SegmentDefinition(
        "asked-price", "Спрашивали цену", "Контакты с явным вопросом о цене.", {"intent": "PRICE"}
    ),
    SegmentDefinition(
        "asked-availability",
        "Спрашивали наличие",
        "Контакты с вопросом о наличии.",
        {"intent": "AVAILABILITY"},
    ),
    SegmentDefinition(
        "asked-delivery",
        "Спрашивали доставку",
        "Контакты с вопросом о доставке.",
        {"intent": "DELIVERY"},
    ),
    SegmentDefinition(
        "asked-quantity",
        "Спрашивали количество",
        "Контакты с количеством или оптовым запросом.",
        {"intent": "QUANTITY"},
    ),
    SegmentDefinition(
        "multi-competitor-2",
        "Сравнивают 2+ конкурентов",
        "Спрос обнаружен минимум у двух продавцов.",
        {"sources": 2},
    ),
    SegmentDefinition(
        "multi-competitor-3",
        "Сравнивают 3+ конкурентов",
        "Спрос обнаружен минимум у трёх продавцов.",
        {"sources": 3},
    ),
    SegmentDefinition(
        "b2b", "B2B и HoReCa", "Явные оптовые или коммерческие признаки.", {"customer_type": "B2B"}
    ),
    SegmentDefinition(
        "quantity-20", "Количество 20+", "Явно указано не менее 20 единиц.", {"quantity": 20}
    ),
    SegmentDefinition(
        "quantity-50", "Количество 50+", "Явно указано не менее 50 единиц.", {"quantity": 50}
    ),
    SegmentDefinition(
        "reactivated",
        "Старые лиды снова активны",
        "Новый сигнал после перерыва не менее 30 дней.",
        {"reactivated": True, "days": 30},
    ),
    SegmentDefinition(
        "rattan-wholesale",
        "Ротанг · оптовый спрос",
        "Ротанг вместе с явным B2B или оптовым интересом.",
        {"product": "RATTAN_FURNITURE", "customer_type": "B2B"},
    ),
    SegmentDefinition(
        "rattan-high-value",
        "Ротанг · высокий потенциал",
        "Ротанг с высокой наблюдаемой коммерческой ценностью.",
        {"product": "RATTAN_FURNITURE", "min_value": 75},
    ),
    # Phase 4 — buyer-role-based segments
    SegmentDefinition(
        "designers",
        "Дизайнеры и комплектаторы",
        "Контакты с ролью дизайнера или комплектатора проекта.",
        {"buyer_role": "DESIGNER_CONTRACTOR"},
    ),
    SegmentDefinition(
        "horeca-b2b",
        "HoReCa и коммерческий сектор",
        "Явный коммерческий спрос: рестораны, кафе, гостиницы, опт.",
        {"buyer_role": "B2B_HORECA"},
    ),
    SegmentDefinition(
        "high-intent-b2c",
        "Горячие розничные покупатели",
        "B2C-покупатели с HOT-статусом и максимальным intent.",
        {"buyer_role": "B2C_CONSUMER", "hot": True},
    ),
    SegmentDefinition(
        "comparison-shoppers",
        "Сравнивают конкурентов (Multi-brand)",
        "Покупатели, замеченные у 2+ разных продавцов.",
        {"sources": 2},
    ),
)


# ---------------------------------------------------------------------------
# Interest Decay / Half-life Policy (V6 Section 21)
# ---------------------------------------------------------------------------

INTEREST_HALF_LIVES: dict[str, float] = {
    "PRICE": 14.0,
    "AVAILABILITY": 10.0,
    "DELIVERY": 14.0,
    "QUANTITY": 30.0,
    "BUY": 21.0,
    "CATALOG": 21.0,
    "FOLLOWER": 180.0,
    "BUSINESS_ROLE": 365.0,
    "BUYER_ROLE": 365.0,
}

INTEREST_PROFILE_ACTIVE_THRESHOLD = 20
INTEREST_ENGINE_VERSION = "3.0"


def calculate_decayed_interest_score(
    score: float,
    topic: str,
    days_elapsed: float,
) -> float:
    """Calculate decayed interest score using exponential half-life decay.

    decayed_score = score * (0.5 ** (days_elapsed / half_life))
    """
    if days_elapsed <= 0:
        return round(score, 2)
    half_life = INTEREST_HALF_LIVES.get(topic.upper(), 30.0)
    decayed = score * (0.5 ** (days_elapsed / half_life))
    return round(max(0.0, min(100.0, decayed)), 2)


# ---------------------------------------------------------------------------
# Similarity weights
# ---------------------------------------------------------------------------


_PRODUCT_WEIGHT = 0.40
_INTENT_WEIGHT = 0.25
_BUYER_ROLE_WEIGHT = 0.20
_VERTICAL_WEIGHT = 0.10
_QUANTITY_BAND_WEIGHT = 0.05


def _jaccard(set_a: set, set_b: set) -> float:
    """Deterministic Jaccard similarity for two sets."""
    if not set_a and not set_b:
        return 1.0
    union = set_a | set_b
    if not union:
        return 0.0
    return len(set_a & set_b) / len(union)


def calculate_contact_similarity(
    intel_a: ContactIntelligence,
    intel_b: ContactIntelligence,
) -> float:
    """
    Deterministic similarity score between two ContactIntelligence records.
    Returns a float in [0.0, 1.0]. No external API calls.
    Grounded in observable public signal data only.
    """
    products_a = {item["value"] for item in (intel_a.product_interests_json or [])}
    products_b = {item["value"] for item in (intel_b.product_interests_json or [])}
    product_sim = _jaccard(products_a, products_b)

    intents_a = {item["value"] for item in (intel_a.top_intents_json or [])}
    intents_b = {item["value"] for item in (intel_b.top_intents_json or [])}
    intent_sim = _jaccard(intents_a, intents_b)

    role_sim = 1.0 if intel_a.primary_buyer_role == intel_b.primary_buyer_role else 0.0
    vertical_sim = 1.0 if intel_a.vertical == intel_b.vertical else 0.0
    quantity_sim = 1.0 if intel_a.quantity_band == intel_b.quantity_band else 0.0

    score = (
        _PRODUCT_WEIGHT * product_sim
        + _INTENT_WEIGHT * intent_sim
        + _BUYER_ROLE_WEIGHT * role_sim
        + _VERTICAL_WEIGHT * vertical_sim
        + _QUANTITY_BAND_WEIGHT * quantity_sim
    )
    return round(min(1.0, max(0.0, score)), 4)


# ---------------------------------------------------------------------------
# Audience Engine
# ---------------------------------------------------------------------------


class AudienceEngine:
    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], hot_threshold: int
    ) -> None:
        self.session_factory = session_factory
        self.hot_threshold = hot_threshold

    async def sync_segments(self) -> int:
        changed = 0
        async with self.session_factory() as session:
            for definition in SEGMENTS:
                segment = await session.scalar(
                    select(AudienceSegment).where(AudienceSegment.slug == definition.slug)
                )
                if segment is None:
                    session.add(
                        AudienceSegment(
                            slug=definition.slug,
                            name=definition.name,
                            description=definition.description,
                            criteria_json=definition.criteria,
                        )
                    )
                    changed += 1
                else:
                    before = (
                        segment.name,
                        segment.description,
                        segment.criteria_json,
                        segment.active,
                    )
                    segment.name = definition.name
                    segment.description = definition.description
                    segment.criteria_json = definition.criteria
                    segment.active = True
                    changed += int(
                        before
                        != (
                            segment.name,
                            segment.description,
                            segment.criteria_json,
                            segment.active,
                        )
                    )
            await session.commit()
        return changed

    async def recalculate_all(self) -> int:
        await self.sync_segments()
        async with self.session_factory() as session:
            contact_ids = list(await session.scalars(select(Contact.id).order_by(Contact.id)))
        for contact_id in contact_ids:
            await self.recalculate_contact(contact_id)
        return len(contact_ids)

    async def _sync_interest_evidence(
        self,
        session: AsyncSession,
        contact_id: int,
        commercial: list[tuple[Lead, Comment]],
        now: datetime,
    ) -> tuple[list[ContactInterestProfile], list[InterestEvidence], set[int]]:
        """Persist deterministic interest observations and rebuild decayed profiles."""
        comment_ids = [comment.id for _lead, comment in commercial]
        signals = (
            list(
                await session.scalars(
                    select(PublicSignal).where(PublicSignal.comment_id.in_(comment_ids))
                )
            )
            if comment_ids
            else []
        )
        signal_by_comment = {signal.comment_id: signal for signal in signals}
        evidence_rows = (
            list(
                await session.scalars(
                    select(Evidence).where(
                        Evidence.public_signal_id.in_([signal.id for signal in signals])
                    )
                )
            )
            if signals
            else []
        )
        evidence_by_signal: dict[int, list[Evidence]] = {}
        for item in evidence_rows:
            evidence_by_signal.setdefault(item.public_signal_id, []).append(item)

        existing = list(
            await session.scalars(
                select(InterestEvidence).where(InterestEvidence.contact_id == contact_id)
            )
        )
        existing_by_key = {item.interest_key: item for item in existing}
        for item in existing:
            item.active = False

        evidenced_comment_ids: set[int] = set()
        for lead, comment in commercial:
            signal = signal_by_comment.get(comment.id)
            if signal is None:
                continue
            candidates = evidence_by_signal.get(signal.id, [])
            if not candidates:
                continue
            requested_ids = {
                int(value)
                for value in (lead.analysis_details or {}).get("evidence_ids", [])
                if isinstance(value, int | str) and str(value).isdigit()
            }
            anchor = next(
                (item for item in candidates if item.id in requested_ids),
                min(candidates, key=lambda item: item.id),
            )
            evidenced_comment_ids.add(comment.id)
            details = lead.analysis_details or {}
            is_v3 = details.get("intelligence_version") == "3.0"
            confidence = self._bounded_int(
                details.get("confidence_score") if is_v3 else details.get("confidence"),
                default=80,
            )
            vertical = getattr(signal.vertical, "value", signal.vertical) or "FURNITURE"
            observations = [("INTENT", str(lead.intent), details.get("intent_score"))]
            if lead.product_category:
                observations.append(
                    ("PRODUCT", str(lead.product_category), details.get("specificity_score"))
                )
            observed_at = self._aware(comment.discovered_at)
            for dimension, topic, component_score in observations:
                half_life = round(
                    INTEREST_HALF_LIVES.get(topic.upper(), 45.0 if dimension == "PRODUCT" else 30.0)
                )
                interest_key = f"{contact_id}:{signal.id}:{dimension}:{topic}"
                item = existing_by_key.get(interest_key)
                if item is None:
                    item = InterestEvidence(
                        interest_key=interest_key,
                        contact_id=contact_id,
                        public_signal_id=signal.id,
                        evidence_id=anchor.id,
                        competitor_id=signal.competitor_id,
                        vertical=str(vertical),
                        dimension=dimension,
                        topic=topic,
                        strength=self._bounded_int(
                            component_score if is_v3 else None,
                            default=lead.lead_score,
                        ),
                        confidence=confidence,
                        half_life_days=half_life,
                        observed_at=observed_at,
                        expires_at=observed_at + timedelta(days=half_life * 4),
                    )
                    session.add(item)
                    existing_by_key[interest_key] = item
                else:
                    item.evidence_id = anchor.id
                    item.competitor_id = signal.competitor_id
                    item.vertical = str(vertical)
                    item.strength = self._bounded_int(
                        component_score if is_v3 else None,
                        default=lead.lead_score,
                    )
                    item.confidence = confidence
                    item.half_life_days = half_life
                    item.observed_at = observed_at
                    item.expires_at = observed_at + timedelta(days=half_life * 4)
                item.active = item.expires_at > now

        await session.flush()
        active_observations = list(
            await session.scalars(
                select(InterestEvidence).where(
                    InterestEvidence.contact_id == contact_id,
                    InterestEvidence.active.is_(True),
                    InterestEvidence.expires_at > now,
                )
            )
        )
        grouped: dict[tuple[str, str, str], list[InterestEvidence]] = {}
        for item in active_observations:
            grouped.setdefault((item.vertical, item.dimension, item.topic), []).append(item)

        profiles = list(
            await session.scalars(
                select(ContactInterestProfile).where(
                    ContactInterestProfile.contact_id == contact_id
                )
            )
        )
        profile_by_scope = {
            (item.vertical, item.dimension, item.topic): item for item in profiles
        }
        active_scopes: set[tuple[str, str, str]] = set()
        for scope, items in grouped.items():
            active_scopes.add(scope)
            effective_scores = []
            for item in items:
                age_days = max(0.0, (now - self._aware(item.observed_at)).total_seconds() / 86400)
                decayed = item.strength * (0.5 ** (age_days / item.half_life_days))
                effective_scores.append((decayed / 100) * (item.confidence / 100))
            current_score = round((1 - prod(1 - min(0.99, score) for score in effective_scores)) * 100)
            combined_confidence = round(
                (1 - prod(1 - min(0.99, item.confidence / 100) for item in items)) * 100
            )
            profile = profile_by_scope.get(scope)
            if profile is None:
                profile = ContactInterestProfile(
                    contact_id=contact_id,
                    vertical=scope[0],
                    dimension=scope[1],
                    topic=scope[2],
                    first_seen_at=min(item.observed_at for item in items),
                    last_seen_at=max(item.observed_at for item in items),
                )
                session.add(profile)
                profile_by_scope[scope] = profile
            profile.current_score = max(0, min(100, current_score))
            profile.confidence = max(0, min(100, combined_confidence))
            profile.first_seen_at = min(item.observed_at for item in items)
            profile.last_seen_at = max(item.observed_at for item in items)
            profile.commercial_signal_count = len({item.public_signal_id for item in items})
            profile.source_count = len({item.competitor_id for item in items})
            profile.competitor_count = profile.source_count
            profile.evidence_ids_json = sorted({item.evidence_id for item in items})
            profile.calculated_at = now
        for scope, profile in profile_by_scope.items():
            if scope not in active_scopes:
                profile.current_score = 0
                profile.confidence = 0
                profile.commercial_signal_count = 0
                profile.source_count = 0
                profile.competitor_count = 0
                profile.evidence_ids_json = []
                profile.calculated_at = now
        await session.flush()
        return list(profile_by_scope.values()), active_observations, evidenced_comment_ids

    async def _sync_outcome_dna(
        self,
        session: AsyncSession,
        contact_id: int,
        commercial: list[tuple[Lead, Comment]],
        now: datetime,
    ) -> None:
        """Snapshot only facts observed before WON, never the outcome itself."""
        won_deals = list(
            await session.scalars(
                select(Deal).where(
                    Deal.contact_id == contact_id,
                    Deal.status == DealStatus.WON,
                )
            )
        )
        if not won_deals:
            return
        observations = list(
            await session.scalars(
                select(InterestEvidence).where(InterestEvidence.contact_id == contact_id)
            )
        )
        for deal in won_deals:
            cutoff = self._aware(deal.won_at or deal.updated_at or now)
            pre_won = [item for item in observations if self._aware(item.observed_at) <= cutoff]
            if not pre_won:
                continue
            pre_won_rows = [
                (lead, comment)
                for lead, comment in commercial
                if self._aware(comment.discovered_at) <= cutoff
            ]
            roles = [
                str((lead.analysis_details or {}).get("buyer_role"))
                for lead, _comment in pre_won_rows
                if (lead.analysis_details or {}).get("buyer_role") not in (None, "UNKNOWN")
            ]
            buyer_role = max(
                set(roles) or {"UNKNOWN"},
                key=lambda role: _BUYER_ROLE_PRIORITY.get(role, 0),
            )
            stage_order = {
                "NON_COMMERCIAL": 0,
                "AWARENESS": 1,
                "CONSIDERATION": 2,
                "PURCHASE_INTENT": 3,
                "READY_TO_BUY": 4,
            }
            stages = [
                str((lead.analysis_details or {}).get("funnel_stage") or "NON_COMMERCIAL")
                for lead, _comment in pre_won_rows
            ]
            commercial_stage = max(
                stages,
                key=lambda stage: stage_order.get(stage, 0),
                default="NON_COMMERCIAL",
            )
            raw_text = " ".join(comment.text.lower() for _lead, comment in pre_won_rows)
            quantity = max(self._extract_explicit_quantities(raw_text), default=0)
            vertical = Counter(item.vertical for item in pre_won).most_common(1)[0][0]
            snapshot = await session.scalar(
                select(OutcomeDNA).where(OutcomeDNA.deal_id == deal.id)
            )
            if snapshot is None:
                snapshot = OutcomeDNA(deal_id=deal.id, contact_id=contact_id)
                session.add(snapshot)
            snapshot.vertical = vertical
            snapshot.cutoff_at = cutoff
            snapshot.product_topics_json = sorted(
                {item.topic for item in pre_won if item.dimension == "PRODUCT"}
            )
            snapshot.intents_json = sorted(
                {item.topic for item in pre_won if item.dimension == "INTENT"}
            )
            snapshot.buyer_role = buyer_role
            snapshot.quantity_band = self._quantity_band(quantity)
            snapshot.commercial_stage = commercial_stage
            snapshot.commercial_signal_count = len(
                {item.public_signal_id for item in pre_won}
            )
            snapshot.source_count = len({item.competitor_id for item in pre_won})
            snapshot.competitor_count = snapshot.source_count
            snapshot.evidence_ids_json = sorted({item.evidence_id for item in pre_won})
            snapshot.engine_version = INTEREST_ENGINE_VERSION
        await session.flush()

    async def recalculate_contact(self, contact_id: int) -> ContactIntelligence:
        await self.sync_segments()
        now = datetime.now(UTC)
        async with self.session_factory() as session:
            contact = await session.get(Contact, contact_id)
            if contact is None:
                raise ValueError(f"Contact {contact_id} was not found")
            rows = (
                await session.execute(
                    select(Lead, Comment)
                    .join(Comment, Comment.id == Lead.comment_id)
                    .where(Lead.contact_id == contact_id)
                    .order_by(Comment.discovered_at)
                )
            ).all()
            comments = list(
                await session.scalars(
                    select(Comment)
                    .where(Comment.contact_id == contact_id)
                    .order_by(Comment.discovered_at)
                )
            )
            intelligence = await session.scalar(
                select(ContactIntelligence).where(ContactIntelligence.contact_id == contact_id)
            )
            if intelligence is None:
                intelligence = ContactIntelligence(
                    contact_id=contact_id,
                    first_seen_at=contact.first_seen_at,
                    last_seen_at=contact.last_seen_at,
                )
                session.add(intelligence)

            commercial = [
                (lead, comment)
                for lead, comment in rows
                if (
                    (lead.analysis_details or {}).get("is_commercial") is True
                    or (
                        (lead.analysis_details or {}).get("intelligence_version")
                        != "3.0"
                        and lead.status != LeadStatus.NOT_LEAD
                        and lead.lead_score >= 50
                    )
                )
            ]
            profiles, interest_observations, evidenced_comment_ids = (
                await self._sync_interest_evidence(
                    session, contact_id, commercial, now
                )
            )
            commercial = [
                (lead, comment)
                for lead, comment in commercial
                if comment.id in evidenced_comment_ids
            ]
            active_profiles = [
                profile
                for profile in profiles
                if profile.current_score >= INTEREST_PROFILE_ACTIVE_THRESHOLD
            ]
            sources = {item.competitor_id for item in interest_observations}
            product_counts = Counter(
                {
                    profile.topic: profile.commercial_signal_count
                    for profile in active_profiles
                    if profile.dimension == "PRODUCT"
                }
            )
            intent_counts = Counter(
                {
                    profile.topic: profile.commercial_signal_count
                    for profile in active_profiles
                    if profile.dimension == "INTENT"
                }
            )
            raw_text = " ".join(comment.text.lower() for _lead, comment in commercial)
            explicit_quantity = max(
                self._extract_explicit_quantities(raw_text),
                default=contact.desired_quantity or 0,
            )
            b2b_decision = B2BPolicy.assess(
                raw_text,
                product="HORECA" if "HORECA" in product_counts else None,
                quantity_override=explicit_quantity or None,
            )
            is_b2b = b2b_decision.role.value == "B2B_HORECA"
            dates = sorted(self._aware(item.observed_at) for item in interest_observations)
            first_seen = min(dates, default=self._aware(contact.first_seen_at))
            last_seen = max(dates, default=self._aware(contact.last_seen_at))
            recency_days = max(0, (now - last_seen).days)
            score_values = [lead.lead_score for lead, _comment in commercial]
            max_score = max(score_values, default=0)
            source_bonus = min(18, max(0, len(sources) - 1) * 9)
            decayed_activity = sum(
                profile.current_score * 0.35
                for profile in active_profiles
                if profile.dimension == "INTENT"
            )
            activity_score = min(
                100,
                round(decayed_activity)
                + source_bonus
                + (
                    20
                    if commercial and recency_days <= 7
                    else 8
                    if commercial and recency_days <= 30
                    else 0
                ),
            )
            value_score = min(
                100,
                max_score
                + (10 if is_b2b else 0)
                + (
                    8
                    if explicit_quantity >= B2BPolicy.PROBABLE_QUANTITY
                    else 0
                ),
            )
            fit_score = min(100, max_score + min(12, len(product_counts) * 4))
            stage_order = {
                "NON_COMMERCIAL": 0,
                "AWARENESS": 1,
                "CONSIDERATION": 2,
                "PURCHASE_INTENT": 3,
                "READY_TO_BUY": 4,
            }
            stages = [
                str((lead.analysis_details or {}).get("funnel_stage") or "NON_COMMERCIAL")
                for lead, _comment in commercial
            ]
            commercial_stage = max(
                stages, key=lambda item: stage_order.get(item, 0), default="NON_COMMERCIAL"
            )
            horizons = [
                str((lead.analysis_details or {}).get("purchase_horizon"))
                for lead, _comment in reversed(commercial)
                if (lead.analysis_details or {}).get("purchase_horizon") not in (None, "UNKNOWN")
            ]

            # ------------------------------------------------------------------
            # Phase 4 — Profile DNA: buyer role aggregation
            # ------------------------------------------------------------------
            observed_roles: list[str] = []
            for lead, _comment in commercial:
                details = lead.analysis_details or {}
                # V2 factor breakdown stores buyer_role directly in analysis_details
                role = details.get("buyer_role") or details.get("v2_buyer_role")
                if role and role != "UNKNOWN":
                    observed_roles.append(str(role))
            # Fallback: derive from B2B flag if no V2 roles yet
            if not observed_roles and is_b2b:
                observed_roles.append("B2B_HORECA")

            unique_roles = sorted(set(observed_roles))
            primary_buyer_role = max(
                unique_roles if unique_roles else ["UNKNOWN"],
                key=lambda r: _BUYER_ROLE_PRIORITY.get(r, 0),
            )

            # ------------------------------------------------------------------
            # Phase 4 — Evidence count from linked public signals
            # ------------------------------------------------------------------
            evidence_count = len({item.evidence_id for item in interest_observations})

            # ------------------------------------------------------------------
            # Phase 4 — Similarity vector (pre-computed, used for get_similar_contacts)
            # ------------------------------------------------------------------
            similarity_vector: dict[str, Any] = {
                "products": sorted(product_counts.keys()),
                "intents": sorted(intent_counts.keys()),
                "buyer_role": primary_buyer_role,
                "vertical": (
                    "ARTIFICIAL_RATTAN" if "RATTAN_FURNITURE" in product_counts else "FURNITURE"
                ),
                "quantity_band": self._quantity_band(explicit_quantity),
            }

            intelligence.vertical = (
                "ARTIFICIAL_RATTAN" if "RATTAN_FURNITURE" in product_counts else "FURNITURE"
            )
            intelligence.commercial_stage = commercial_stage
            intelligence.intent_strength = max_score
            intelligence.signal_count = len(comments)
            intelligence.commercial_signal_count = len(commercial)
            intelligence.source_count = len(sources)
            intelligence.competitor_count = len(sources)
            intelligence.activity_score = activity_score
            intelligence.value_score = value_score
            intelligence.fit_score = fit_score
            intelligence.customer_type = "B2B" if is_b2b else "B2C"
            intelligence.quantity_band = self._quantity_band(explicit_quantity)
            intelligence.purchase_horizon = horizons[0] if horizons else None
            intelligence.product_interests_json = self._ranked_profiles(
                active_profiles, "PRODUCT"
            )
            intelligence.top_intents_json = self._ranked_profiles(
                active_profiles, "INTENT"
            )
            intelligence.export_eligibility = (
                ExportEligibility.FIRST_PARTY_ELIGIBLE
                if contact.phone and contact.qualification_updated_at is not None
                else ExportEligibility.NOT_EXPORTABLE
            )
            intelligence.first_seen_at = first_seen
            intelligence.last_seen_at = last_seen
            # Phase 4 DNA
            intelligence.primary_buyer_role = primary_buyer_role
            intelligence.buyer_roles_json = unique_roles
            intelligence.evidence_count = evidence_count
            intelligence.similarity_vector_json = similarity_vector
            await session.flush()

            segments = list(
                await session.scalars(
                    select(AudienceSegment).where(AudienceSegment.active.is_(True))
                )
            )
            reactivated = bool(
                len(dates) >= 2 and dates[-1] - dates[-2] >= timedelta(days=30)
            )
            facts = {
                "hot": max_score >= self.hot_threshold,
                "recency_days": recency_days,
                "products": set(product_counts),
                "intents": set(intent_counts),
                "sources": len(sources),
                "customer_type": intelligence.customer_type,
                "quantity": explicit_quantity,
                "value": value_score,
                "reactivated": reactivated,
                "buyer_role": primary_buyer_role,
                "profiles": {
                    (profile.dimension, profile.topic): profile
                    for profile in active_profiles
                },
                "evidence_ids": sorted(
                    {item.evidence_id for item in interest_observations}
                ),
            }
            for segment in segments:
                active, reasons, evidence_ids, expires_at = self._evaluate(
                    segment.criteria_json, facts, last_seen
                )
                membership = await session.scalar(
                    select(AudienceMembership).where(
                        AudienceMembership.segment_id == segment.id,
                        AudienceMembership.contact_id == contact_id,
                    )
                )
                if membership is None:
                    membership = AudienceMembership(
                        segment_id=segment.id,
                        contact_id=contact_id,
                    )
                    session.add(membership)
                membership.active = active
                membership.confidence = min(98, max(50, value_score if active else 50))
                membership.evidence_json = [reason["text"] for reason in reasons]
                membership.reasons_json = reasons
                membership.evidence_ids_json = evidence_ids
                membership.engine_version = INTEREST_ENGINE_VERSION
                membership.expires_at = expires_at
                membership.evaluated_at = now
            await self._sync_outcome_dna(session, contact_id, commercial, now)
            await session.commit()
            return intelligence

    async def get_similar_contacts(
        self, contact_id: int, limit: int = 5
    ) -> list[dict[str, Any]]:
        """
        Find similar contacts by deterministic similarity scoring.
        Compares pre-computed similarity vectors in ContactIntelligence.
        No external API calls. Returns contacts ranked by similarity descending.
        """
        async with self.session_factory() as session:
            source = await session.scalar(
                select(ContactIntelligence).where(
                    ContactIntelligence.contact_id == contact_id
                )
            )
            if source is None:
                return []
            all_intel = list(
                await session.scalars(
                    select(ContactIntelligence).where(
                        ContactIntelligence.contact_id != contact_id
                    )
                )
            )

        scored = [
            {"contact_id": intel.contact_id, "score": calculate_contact_similarity(source, intel)}
            for intel in all_intel
        ]
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:limit]

    async def build_audience_export(
        self,
        segment_slug: str,
        require_export_eligible: bool = True,
    ) -> list[dict[str, Any]]:
        """
        Build export records for a segment.
        Strictly enforces ExportEligibility.FIRST_PARTY_ELIGIBLE when
        require_export_eligible=True (the default).
        Never includes synthetic or inferred private data.
        """
        async with self.session_factory() as session:
            segment = await session.scalar(
                select(AudienceSegment).where(AudienceSegment.slug == segment_slug)
            )
            if segment is None:
                return []

            query = (
                select(Contact, ContactIntelligence)
                .join(ContactIntelligence, ContactIntelligence.contact_id == Contact.id)
                .join(
                    AudienceMembership,
                    (AudienceMembership.contact_id == Contact.id)
                    & (AudienceMembership.segment_id == segment.id)
                    & (AudienceMembership.active.is_(True)),
                )
            )
            if require_export_eligible:
                query = query.where(
                    ContactIntelligence.export_eligibility
                    == ExportEligibility.FIRST_PARTY_ELIGIBLE
                )

            rows = (await session.execute(query)).all()

        return [
            {
                "contact_id": contact.id,
                "username": contact.username,
                "phone": contact.phone,
                "primary_buyer_role": intel.primary_buyer_role,
                "segment": segment_slug,
                "value_score": intel.value_score,
                "evidence_count": intel.evidence_count,
                "export_eligibility": intel.export_eligibility.value,
            }
            for contact, intel in rows
        ]

    @staticmethod
    def _evaluate(criteria: dict, facts: dict, last_seen: datetime):
        reasons: list[dict[str, Any]] = []
        evidence_ids: set[int] = set()
        active = True
        expires_at = None

        def add_reason(
            criterion: str,
            text: str,
            ids: list[int] | None = None,
            score: int | None = None,
        ) -> None:
            normalized_ids = sorted(set(ids or []))
            evidence_ids.update(normalized_ids)
            reason: dict[str, Any] = {
                "criterion": criterion,
                "text": text,
                "evidence_ids": normalized_ids,
                "observed_at": last_seen.isoformat(),
            }
            if score is not None:
                reason["score"] = score
            reasons.append(reason)

        if criteria.get("hot"):
            active &= bool(facts["hot"])
            add_reason("HOT", "HOT-порог достигнут", facts["evidence_ids"], facts["value"])
        if days := criteria.get("days"):
            active &= int(facts["recency_days"]) < int(days)
            expires_at = last_seen + timedelta(days=int(days))
            add_reason("RECENCY", f"коммерческая активность за {days} дн.", facts["evidence_ids"])
        if product := criteria.get("product"):
            profile = facts["profiles"].get(("PRODUCT", product))
            active &= profile is not None
            if profile is not None:
                product_expiry = profile.last_seen_at + timedelta(
                    days=round(INTEREST_HALF_LIVES.get(product, 45.0) * 4)
                )
                expires_at = min(expires_at, product_expiry) if expires_at else product_expiry
                add_reason(
                    "PRODUCT",
                    f"{profile.commercial_signal_count} подтвержд. сигнал(а): {product}",
                    profile.evidence_ids_json,
                    profile.current_score,
                )
        if intent := criteria.get("intent"):
            profile = facts["profiles"].get(("INTENT", intent))
            active &= profile is not None
            if profile is not None:
                intent_expiry = profile.last_seen_at + timedelta(
                    days=round(INTEREST_HALF_LIVES.get(intent, 30.0) * 4)
                )
                expires_at = min(expires_at, intent_expiry) if expires_at else intent_expiry
                add_reason(
                    "INTENT",
                    f"подтверждённое намерение: {intent}",
                    profile.evidence_ids_json,
                    profile.current_score,
                )
        if sources := criteria.get("sources"):
            active &= int(facts["sources"]) >= int(sources)
            add_reason(
                "SOURCES",
                f"коммерческих источников: {facts['sources']}",
                facts["evidence_ids"],
            )
        if customer_type := criteria.get("customer_type"):
            active &= facts["customer_type"] == customer_type
            add_reason("CUSTOMER_TYPE", f"тип: {customer_type}", facts["evidence_ids"])
        if quantity := criteria.get("quantity"):
            active &= int(facts["quantity"]) >= int(quantity)
            add_reason("QUANTITY", f"количество: {facts['quantity']}", facts["evidence_ids"])
        if min_value := criteria.get("min_value"):
            active &= int(facts["value"]) >= int(min_value)
            add_reason("VALUE", f"value score: {facts['value']}", facts["evidence_ids"], facts["value"])
        if criteria.get("reactivated"):
            active &= bool(facts["reactivated"])
            add_reason("REACTIVATED", "возвращение после паузы 30+ дней", facts["evidence_ids"])
        # Phase 4 — buyer role matching
        if buyer_role := criteria.get("buyer_role"):
            active &= facts.get("buyer_role") == buyer_role
            add_reason("BUYER_ROLE", f"роль покупателя: {buyer_role}", facts["evidence_ids"])
        return (
            active,
            reasons if active else [],
            sorted(evidence_ids) if active else [],
            expires_at,
        )

    @staticmethod
    def _ranked_profiles(
        profiles: list[ContactInterestProfile], dimension: str
    ) -> list[dict[str, object]]:
        ranked = sorted(
            (profile for profile in profiles if profile.dimension == dimension),
            key=lambda profile: (profile.current_score, profile.last_seen_at),
            reverse=True,
        )
        return [
            {
                "value": profile.topic,
                "count": profile.commercial_signal_count,
                "confidence": profile.confidence,
                "current_score": profile.current_score,
                "source_count": profile.source_count,
                "evidence_ids": profile.evidence_ids_json,
            }
            for profile in ranked[:8]
        ]

    @staticmethod
    def _ranked(counter: Counter) -> list[dict[str, object]]:
        total = sum(counter.values()) or 1
        return [
            {"value": value, "count": count, "confidence": round(count / total * 100)}
            for value, count in counter.most_common(8)
        ]

    @staticmethod
    def _quantity_band(value: int) -> str | None:
        if value >= 50:
            return "50_PLUS"
        if value >= 20:
            return "20_PLUS"
        if value > 0:
            return "EXPLICIT"
        return None

    @staticmethod
    def _extract_explicit_quantities(text: str) -> list[int]:
        """Return quantities with an explicit unit, never bare price-like numbers."""
        unit_pattern = (
            r"шт(?:\.|ук(?:а|и|ов)?)?|dona|дона|та|персон|киши|kishi|kishilik|кишилик|"
            r"стул(?:а|ов|ья|ьев)?|крес(?:ло|ла|ел)|стол(?:а|ов)?|комплект(?:а|ов)?"
        )
        return [
            int(match.group(1))
            for match in re.finditer(rf"\b(\d{{1,4}})\s*(?:{unit_pattern})\b", text)
        ]

    @staticmethod
    def _bounded_int(value: object, *, default: int) -> int:
        try:
            parsed = int(value) if value is not None else int(default)
        except (TypeError, ValueError):
            parsed = int(default)
        return max(0, min(100, parsed))

    @staticmethod
    def _aware(value: datetime) -> datetime:
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
