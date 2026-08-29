from __future__ import annotations

import logging
from dataclasses import asdict, dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import (
    AudienceMembership,
    AudienceSegment,
    ContactEventType,
    ContactIntelligence,
    SignificantChange,
)
from app.db.repositories.events import ContactEventRepository

logger = logging.getLogger(__name__)

CHANGE_LABELS = {
    "NEW_COMPETITOR": "интерес появился у нового конкурента",
    "NEW_STRONG_INTENT": "появилось новое сильное покупательское намерение",
    "NEW_PRODUCT": "появилась новая товарная категория",
    "SIGNIFICANT_QUANTITY": "обнаружено значимое количество",
    "B2B_DETECTED": "обнаружен B2B / HoReCa спрос",
    "ENTERED_HOT": "контакт вошёл в HOT-аудиторию",
    "ENTERED_HIGH_VALUE": "контакт стал high-value",
    "REACTIVATED": "контакт вернулся после длительной паузы",
    "VALUE_INCREASE": "приоритет существенно вырос",
    "STAGE_ADVANCED": "контакт перешёл на следующую коммерческую стадию",
}

STAGE_ORDER = {
    "NON_COMMERCIAL": 0,
    "AWARENESS": 1,
    "CONSIDERATION": 2,
    "PURCHASE_INTENT": 3,
    "READY_TO_BUY": 4,
}

QUANTITY_ORDER = {None: 0, "EXPLICIT": 1, "20_PLUS": 2, "50_PLUS": 3}


@dataclass(frozen=True, slots=True)
class IntelligenceSnapshot:
    signal_count: int
    commercial_signal_count: int
    competitor_count: int
    activity_score: int
    value_score: int
    fit_score: int
    commercial_stage: str
    intent_strength: int
    customer_type: str
    quantity_band: str | None
    products: tuple[str, ...]
    intents: tuple[str, ...]
    audiences: tuple[str, ...]

    @property
    def priority(self) -> int:
        return min(100, round(self.value_score * 0.65 + self.activity_score * 0.35))


class SignificantChangeDetector:
    """Persist one explainable, retry-safe material change for each analyzed signal."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        hot_threshold: int,
        high_value_threshold: int = 75,
        priority_delta_threshold: int = 15,
    ) -> None:
        self.session_factory = session_factory
        self.hot_threshold = hot_threshold
        self.high_value_threshold = high_value_threshold
        self.priority_delta_threshold = priority_delta_threshold

    async def snapshot(self, contact_id: int) -> IntelligenceSnapshot | None:
        async with self.session_factory() as session:
            intelligence = await session.scalar(
                select(ContactIntelligence).where(
                    ContactIntelligence.contact_id == contact_id
                )
            )
            if intelligence is None:
                return None
            audiences = tuple(
                await session.scalars(
                    select(AudienceSegment.slug)
                    .join(
                        AudienceMembership,
                        AudienceMembership.segment_id == AudienceSegment.id,
                    )
                    .where(
                        AudienceMembership.contact_id == contact_id,
                        AudienceMembership.active.is_(True),
                    )
                    .order_by(AudienceSegment.slug)
                )
            )
            return self._from_model(intelligence, audiences)

    async def detect_and_persist(
        self,
        contact_id: int,
        lead_id: int,
        before: IntelligenceSnapshot | None,
    ) -> SignificantChange | None:
        if before is None or before.signal_count < 1:
            logger.info("significant_change_skipped contact_id=%s reason=no_history", contact_id)
            return None
        after = await self.snapshot(contact_id)
        if after is None or after.signal_count <= before.signal_count:
            logger.info(
                "significant_change_skipped contact_id=%s reason=no_new_signal before=%s after=%s",
                contact_id,
                before.signal_count,
                after.signal_count if after is not None else None,
            )
            return None
        change_types = self._detect(before, after)
        if not change_types:
            logger.info(
                "significant_change_skipped contact_id=%s reason=below_threshold priority=%s_to_%s",
                contact_id,
                before.priority,
                after.priority,
            )
            return None
        summary = self._summary(change_types, before, after)
        severity = self._severity(change_types, after)
        async with self.session_factory() as session:
            existing = await session.scalar(
                select(SignificantChange).where(SignificantChange.lead_id == lead_id)
            )
            if existing is not None:
                return existing
            change = SignificantChange(
                contact_id=contact_id,
                lead_id=lead_id,
                primary_type=change_types[0],
                change_types_json=change_types,
                severity=severity,
                previous_priority=before.priority,
                current_priority=after.priority,
                summary=summary,
                before_json=asdict(before),
                after_json=asdict(after),
            )
            session.add(change)
            try:
                await session.flush()
                await ContactEventRepository(session).add(
                    contact_id,
                    ContactEventType.SIGNIFICANT_CHANGE,
                    lead_id=lead_id,
                    payload={
                        "change_id": change.id,
                        "types": change_types,
                        "severity": severity,
                        "from": before.priority,
                        "to": after.priority,
                        "summary": summary,
                    },
                )
                await session.commit()
            except IntegrityError:
                await session.rollback()
                return await session.scalar(
                    select(SignificantChange).where(SignificantChange.lead_id == lead_id)
                )
            logger.info(
                "significant_change_persisted change_id=%s contact_id=%s types=%s",
                change.id,
                contact_id,
                change_types,
            )
            return change

    def _detect(
        self, before: IntelligenceSnapshot, after: IntelligenceSnapshot
    ) -> list[str]:
        changes: list[str] = []
        new_products = set(after.products) - set(before.products)
        new_intents = set(after.intents) - set(before.intents)
        entered_audiences = set(after.audiences) - set(before.audiences)
        if after.competitor_count > before.competitor_count:
            changes.append("NEW_COMPETITOR")
        if new_intents and after.intent_strength >= self.hot_threshold:
            changes.append("NEW_STRONG_INTENT")
        if new_products:
            changes.append("NEW_PRODUCT")
        if QUANTITY_ORDER.get(after.quantity_band, 0) >= 2 and QUANTITY_ORDER.get(
            after.quantity_band, 0
        ) > QUANTITY_ORDER.get(before.quantity_band, 0):
            changes.append("SIGNIFICANT_QUANTITY")
        if before.customer_type != "B2B" and after.customer_type == "B2B":
            changes.append("B2B_DETECTED")
        if any(slug.startswith("hot-") for slug in entered_audiences):
            changes.append("ENTERED_HOT")
        if (
            before.value_score < self.high_value_threshold
            <= after.value_score
        ):
            changes.append("ENTERED_HIGH_VALUE")
        if "furniture-reactivated" in entered_audiences:
            changes.append("REACTIVATED")
        if (
            after.priority >= self.hot_threshold
            and after.priority - before.priority >= self.priority_delta_threshold
        ):
            changes.append("VALUE_INCREASE")
        if STAGE_ORDER.get(after.commercial_stage, 0) > STAGE_ORDER.get(
            before.commercial_stage, 0
        ):
            changes.append("STAGE_ADVANCED")
        return changes

    @staticmethod
    def _summary(
        change_types: list[str],
        before: IntelligenceSnapshot,
        after: IntelligenceSnapshot,
    ) -> str:
        labels = [CHANGE_LABELS[item] for item in change_types[:3]]
        details = "; ".join(labels)
        return (
            f"{details}. Источников: {before.competitor_count} → "
            f"{after.competitor_count}; приоритет: {before.priority} → {after.priority}."
        )

    @staticmethod
    def _severity(change_types: list[str], after: IntelligenceSnapshot) -> str:
        critical = {"B2B_DETECTED", "ENTERED_HOT", "ENTERED_HIGH_VALUE"}
        if critical.intersection(change_types) and after.priority >= 80:
            return "CRITICAL"
        if {"NEW_COMPETITOR", "VALUE_INCREASE", "STAGE_ADVANCED"}.intersection(
            change_types
        ):
            return "HIGH"
        return "MEDIUM"

    @staticmethod
    def _from_model(
        intelligence: ContactIntelligence, audiences: tuple[str, ...]
    ) -> IntelligenceSnapshot:
        return IntelligenceSnapshot(
            signal_count=intelligence.signal_count,
            commercial_signal_count=intelligence.commercial_signal_count,
            competitor_count=intelligence.competitor_count,
            activity_score=intelligence.activity_score,
            value_score=intelligence.value_score,
            fit_score=intelligence.fit_score,
            commercial_stage=intelligence.commercial_stage,
            intent_strength=intelligence.intent_strength,
            customer_type=intelligence.customer_type,
            quantity_band=intelligence.quantity_band,
            products=tuple(
                str(item["value"])
                for item in intelligence.product_interests_json
                if item.get("value")
            ),
            intents=tuple(
                str(item["value"])
                for item in intelligence.top_intents_json
                if item.get("value")
            ),
            audiences=audiences,
        )
