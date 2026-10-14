from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from itertools import pairwise

from app.schemas.leads import CommercialSignalQuality, Intent
from app.services.b2b_policy import B2BDecision, B2BPolicy

HALF_LIFE_DAYS: dict[Intent, float] = {
    Intent.PRICE: 14.0,
    Intent.AVAILABILITY: 10.0,
    Intent.DELIVERY: 14.0,
    Intent.BUY: 21.0,
    Intent.QUANTITY: 30.0,
    Intent.CATALOG: 21.0,
    Intent.CONTACT: 21.0,
    Intent.COLOR: 21.0,
    Intent.SIZE: 21.0,
}

SEQUENCE_BONUSES: dict[tuple[Intent, Intent], int] = {
    (Intent.PRICE, Intent.AVAILABILITY): 7,
    (Intent.AVAILABILITY, Intent.DELIVERY): 8,
    (Intent.PRICE, Intent.QUANTITY): 9,
    (Intent.CATALOG, Intent.PRICE): 6,
    (Intent.PRICE, Intent.CONTACT): 8,
    (Intent.QUANTITY, Intent.DELIVERY): 9,
    (Intent.BUY, Intent.CONTACT): 8,
}


@dataclass(frozen=True, slots=True)
class HistoricalSignal:
    competitor: str
    intent: Intent
    quality: CommercialSignalQuality
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class LeadScoreV3:
    quality: CommercialSignalQuality
    intent_score: int
    activity_score: int
    specificity_score: int
    value_score: int
    fit_score: int
    source_quality_score: int
    confidence_score: int
    priority_score: int
    history_boost: int
    sequence_score: int
    validated_commercial_count: int
    validated_competitor_count: int
    b2b: B2BDecision


def signal_quality(*, is_lead: bool, intent: Intent) -> CommercialSignalQuality:
    if not is_lead or intent in {Intent.REACTION, Intent.SPAM, Intent.OTHER}:
        return CommercialSignalQuality.NON_COMMERCIAL
    if intent in {Intent.BUY, Intent.QUANTITY}:
        return CommercialSignalQuality.STRONG_COMMERCIAL
    if intent in {
        Intent.PRICE,
        Intent.AVAILABILITY,
        Intent.DELIVERY,
        Intent.CATALOG,
        Intent.CONTACT,
        Intent.COLOR,
        Intent.SIZE,
        Intent.LOCATION,
    }:
        return CommercialSignalQuality.MEDIUM_COMMERCIAL
    return CommercialSignalQuality.WEAK_COMMERCIAL


def infer_historical_intent(text: str) -> Intent | None:
    value = " ".join(text.lower().replace("ё", "е").split())
    if not value:
        return None
    if any(word in value for word in ("цена", "сколько стоит", "narx", "qancha", "нарх")):
        return Intent.PRICE
    if any(word in value for word in ("достав", "yetkaz", "етказ")):
        return Intent.DELIVERY
    if any(word in value for word in ("в наличии", "bormi", "борми", "mavjud")):
        return Intent.AVAILABILITY
    if B2BPolicy.extract_quantity(value) is not None:
        return Intent.QUANTITY
    if any(word in value for word in ("каталог", "catalog", "katalog")):
        return Intent.CATALOG
    if any(word in value for word in ("купить", "заказать", "buyurtma", "olmoqchiman", "керак")):
        return Intent.BUY
    if any(word in value for word in ("напишите", "связаться", "yozing", "ёзинг")):
        return Intent.CONTACT
    return None


class LeadScorerV3:
    VERSION = "3.1"
    MAX_HISTORY_AGE_DAYS = 90

    @classmethod
    def score(
        cls,
        *,
        is_lead: bool,
        intent: Intent,
        legacy_intent_score: int,
        text: str,
        product: str | None,
        evidence_ids: list[int],
        history: list[HistoricalSignal],
        current_competitor: str,
        urgency_score: int,
        now: datetime | None = None,
    ) -> LeadScoreV3:
        quality = signal_quality(is_lead=is_lead, intent=intent)
        b2b = B2BPolicy.assess(text, product=product)
        reference = cls._utc(now or datetime.now(UTC))
        commercial = cls._usable_history(history, reference)
        history_boost, sequence_score = cls._history_scores(
            commercial,
            intent,
            current_competitor=current_competitor,
            now=reference,
        )
        competitor_count = len(
            {item.competitor for item in commercial if item.competitor}
            | ({current_competitor} if quality != CommercialSignalQuality.NON_COMMERCIAL else set())
        )

        activity_base = {
            CommercialSignalQuality.NON_COMMERCIAL: 0,
            CommercialSignalQuality.WEAK_COMMERCIAL: 45,
            CommercialSignalQuality.MEDIUM_COMMERCIAL: 75,
            CommercialSignalQuality.STRONG_COMMERCIAL: 95,
        }[quality]
        activity_score = min(100, activity_base + history_boost + sequence_score)
        quantity = b2b.quantity
        specificity_score = 10 if quality == CommercialSignalQuality.NON_COMMERCIAL else 55
        if product:
            specificity_score += 20
        if quantity is not None:
            specificity_score += 25
        elif any(char.isdigit() for char in text):
            specificity_score += 10
        specificity_score = min(100, specificity_score)

        value_score = {
            CommercialSignalQuality.NON_COMMERCIAL: 0,
            CommercialSignalQuality.WEAK_COMMERCIAL: 35,
            CommercialSignalQuality.MEDIUM_COMMERCIAL: 60,
            CommercialSignalQuality.STRONG_COMMERCIAL: 80,
        }[quality]
        if b2b.role.value == "B2B_HORECA":
            value_score = max(value_score, 90 if b2b.tier != "STRONG" else 100)
        fit_score = 0 if quality == CommercialSignalQuality.NON_COMMERCIAL else (95 if product else 65)
        source_quality_score = 90
        confidence_score = cls._confidence(
            quality=quality,
            evidence_ids=evidence_ids,
            product=product,
            intent=intent,
        )
        priority = round(
            0.55 * max(0, min(100, legacy_intent_score))
            + 0.15 * activity_score
            + 0.10 * specificity_score
            + 0.08 * value_score
            + 0.05 * fit_score
            + 0.04 * source_quality_score
            + 0.03 * urgency_score
        )
        if quality == CommercialSignalQuality.NON_COMMERCIAL:
            priority = min(priority, 15)

        return LeadScoreV3(
            quality=quality,
            intent_score=max(0, min(100, legacy_intent_score)),
            activity_score=activity_score,
            specificity_score=specificity_score,
            value_score=value_score,
            fit_score=fit_score,
            source_quality_score=source_quality_score,
            confidence_score=confidence_score,
            priority_score=max(0, min(100, priority)),
            history_boost=history_boost,
            sequence_score=sequence_score,
            validated_commercial_count=len(commercial),
            validated_competitor_count=competitor_count,
            b2b=b2b,
        )

    @staticmethod
    def _utc(value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)

    @classmethod
    def _usable_history(cls, history: list[HistoricalSignal], now: datetime) -> list[HistoricalSignal]:
        return [replace(item, observed_at=cls._utc(item.observed_at)) for item in history
                if item.quality != CommercialSignalQuality.NON_COMMERCIAL
                and 0 <= (now - cls._utc(item.observed_at)).total_seconds() <= cls.MAX_HISTORY_AGE_DAYS * 86400]

    @classmethod
    def _history_scores(
        cls,
        history: list[HistoricalSignal],
        current_intent: Intent,
        *,
        current_competitor: str = "",
        now: datetime | None = None,
    ) -> tuple[int, int]:
        now = cls._utc(now or datetime.now(UTC))
        counts: dict[Intent, int] = {}
        history_score = 0.0
        ordered = sorted(cls._usable_history(history, now), key=lambda item: item.observed_at)
        source_weights: dict[str, float] = {}
        for item in ordered:
            counts[item.intent] = counts.get(item.intent, 0) + 1
            age_days = max(0.0, (now - item.observed_at).total_seconds() / 86400)
            half_life = HALF_LIFE_DAYS.get(item.intent, 30.0)
            decay = 0.5 ** (age_days / half_life)
            diminishing = 1 / math.sqrt(counts[item.intent])
            history_score += 4.0 * decay * diminishing
            if item.competitor and item.competitor != current_competitor:
                source_weights[item.competitor] = max(source_weights.get(item.competitor, 0), decay)
        # The cross-source bonus ages with the evidence establishing that source.
        history_score += min(6, max(0, sum(source_weights.values()) - (0 if current_competitor else 1)) * 3)

        sequence = [*ordered, HistoricalSignal(current_competitor, current_intent,
                                               CommercialSignalQuality.MEDIUM_COMMERCIAL, now)]
        sequence_score = 0.0
        for left, right in pairwise(sequence):
            age = max(0, (now - left.observed_at).total_seconds() / 86400)
            half_life = min(HALF_LIFE_DAYS.get(left.intent, 30), HALF_LIFE_DAYS.get(right.intent, 30))
            sequence_score += SEQUENCE_BONUSES.get((left.intent, right.intent), 0) * 0.5 ** (age / half_life)
        return min(15, round(history_score)), min(18, round(sequence_score))

    @staticmethod
    def _confidence(
        *,
        quality: CommercialSignalQuality,
        evidence_ids: list[int],
        product: str | None,
        intent: Intent,
    ) -> int:
        confidence = {
            CommercialSignalQuality.NON_COMMERCIAL: 88,
            CommercialSignalQuality.WEAK_COMMERCIAL: 48,
            CommercialSignalQuality.MEDIUM_COMMERCIAL: 80,
            CommercialSignalQuality.STRONG_COMMERCIAL: 90,
        }[quality]
        if product:
            confidence += 5
        if not evidence_ids:
            confidence -= 15
        if intent == Intent.OTHER:
            confidence -= 15
        return max(20, min(98, confidence))


def parse_observed_at(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError):
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
