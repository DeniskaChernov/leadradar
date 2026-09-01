from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import ClassVar


@dataclass(frozen=True, slots=True)
class CompetitorMonitoringFacts:
    competitor_id: int
    handle: str
    tier: str
    last_scanned_at: datetime | None
    newest_reel_at: datetime | None
    last_commercial_at: datetime | None
    last_hot_at: datetime | None
    last_b2b_at: datetime | None
    commercial_signals_30d: int
    scan_error_count: int


@dataclass(frozen=True, slots=True)
class MonitoringDecision:
    state: str
    interval_hours: int
    next_due_at: datetime
    priority_score: int
    reasons: tuple[str, ...]


class AdaptiveMonitoringPolicy:
    """Детерминированная частота мониторинга по наблюдаемой коммерческой активности."""

    VERSION = "adaptive-v1"
    INTERVAL_HOURS: ClassVar[dict[str, int]] = {
        "ACTIVE": 4,
        "WARM": 12,
        "COLD": 48,
        "DORMANT": 72,
    }
    STATE_PRIORITY: ClassVar[dict[str, int]] = {
        "ACTIVE": 100,
        "WARM": 70,
        "COLD": 40,
        "DORMANT": 10,
    }
    TIER_PRIORITY: ClassVar[dict[str, int]] = {"A": 20, "B": 10, "C": 0}

    @classmethod
    def decide(
        cls,
        facts: CompetitorMonitoringFacts,
        *,
        now: datetime | None = None,
    ) -> MonitoringDecision:
        now = now or datetime.now(UTC)
        reel_age = cls._age_days(facts.newest_reel_at, now)
        commercial_age = cls._age_days(facts.last_commercial_at, now)
        hot_age = cls._age_days(facts.last_hot_at, now)
        b2b_age = cls._age_days(facts.last_b2b_at, now)
        reasons: list[str] = []

        if (
            cls._within(reel_age, 1)
            or cls._within(commercial_age, 1)
            or cls._within(hot_age, 7)
            or cls._within(b2b_age, 7)
        ):
            state = "ACTIVE"
            if cls._within(reel_age, 1):
                reasons.append("NEW_REEL_24H")
            if cls._within(commercial_age, 1):
                reasons.append("COMMERCIAL_ACTIVITY_24H")
            if cls._within(hot_age, 7):
                reasons.append("RECENT_HOT_7D")
            if cls._within(b2b_age, 7):
                reasons.append("RECENT_B2B_7D")
        elif any(
            cls._within(age, 3)
            for age in (reel_age, commercial_age, hot_age, b2b_age)
        ):
            state = "WARM"
            reasons.append("USEFUL_ACTIVITY_3D")
        elif any(
            cls._within(age, 14)
            for age in (reel_age, commercial_age, hot_age, b2b_age)
        ):
            state = "COLD"
            reasons.append("USEFUL_ACTIVITY_14D")
        else:
            state = "DORMANT"
            reasons.append("NO_USEFUL_ACTIVITY_14D")

        interval_hours = cls.INTERVAL_HOURS[state]
        last_scan = cls._aware(facts.last_scanned_at)
        next_due_at = (
            last_scan + timedelta(hours=interval_hours)
            if last_scan is not None
            else now
        )
        overdue_hours = max(0, int((now - next_due_at).total_seconds() // 3600))
        yield_score = min(20, facts.commercial_signals_30d * 2)
        priority = (
            cls.STATE_PRIORITY[state]
            + cls.TIER_PRIORITY.get(facts.tier.upper(), 0)
            + min(30, overdue_hours)
            + yield_score
            - min(30, facts.scan_error_count * 5)
        )
        return MonitoringDecision(
            state=state,
            interval_hours=interval_hours,
            next_due_at=next_due_at,
            priority_score=max(0, priority),
            reasons=tuple(reasons),
        )

    @staticmethod
    def _aware(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)

    @classmethod
    def _age_days(cls, value: datetime | None, now: datetime) -> float | None:
        aware = cls._aware(value)
        if aware is None:
            return None
        return max(0.0, (now - aware).total_seconds() / 86400)

    @staticmethod
    def _within(age: float | None, days: int) -> bool:
        return age is not None and age <= days
