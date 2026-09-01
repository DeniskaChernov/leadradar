"""View-model для /audiences/quality: health snapshots и overlap analytics."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from itertools import combinations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import (
    AudienceMembership,
    AudienceSegment,
    ContactIntelligence,
    Deal,
    DealStatus,
    ExportEligibility,
    Vertical,
)
from app.services.audience_service import AudienceEngine

_RATIO_QUANT = Decimal("0.01")
_STALE_DAYS = 30
_LOW_DATA_THRESHOLD = 5
_MIN_HEALTHY_CONFIDENCE = 60
_NOISY_CONFIDENCE = 45
_UNKNOWN_RATIO_THRESHOLD = Decimal("0.50")
_STALE_RATIO_THRESHOLD = Decimal("0.50")


@dataclass(frozen=True, slots=True)
class AudienceHealthSnapshot:
    segment_slug: str
    segment_name: str
    segment_status: str
    audience_level: str
    status: str
    active_members: int
    new_members_7d: int
    expired_7d: int
    avg_confidence: int
    avg_intent_score: int
    avg_evidence_count: int
    avg_source_count: int
    stale_ratio: Decimal
    unknown_ratio: Decimal
    won_count: int
    won_rate: Decimal | None
    exportable_count: int
    issues: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AudienceOverlapRow:
    left_slug: str
    left_name: str
    right_slug: str
    right_name: str
    intersection: int
    left_only: int
    right_only: int
    jaccard: Decimal


@dataclass(frozen=True, slots=True)
class AudienceQualityPageSnapshot:
    generated_at: datetime
    vertical: str
    health_rows: tuple[AudienceHealthSnapshot, ...]
    overlap_rows: tuple[AudienceOverlapRow, ...]
    total_active_members: int
    healthy_count: int
    needs_review_count: int


class AudienceQualityService:
    """Собирает health/overlap метрики из БД без внешних вызовов."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def snapshot(self, vertical: str = "FURNITURE") -> AudienceQualityPageSnapshot:
        now = datetime.now(UTC)
        window_7d = now - timedelta(days=7)
        try:
            selected_vertical = Vertical(vertical)
        except ValueError:
            selected_vertical = Vertical.FURNITURE

        async with self.session_factory() as session:
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
            if not segments:
                return AudienceQualityPageSnapshot(
                    generated_at=now,
                    vertical=selected_vertical.value,
                    health_rows=(),
                    overlap_rows=(),
                    total_active_members=0,
                    healthy_count=0,
                    needs_review_count=0,
                )

            segment_ids = [segment.id for segment in segments]
            rows = (
                await session.execute(
                    select(
                        AudienceMembership,
                        AudienceSegment,
                        ContactIntelligence,
                        Deal.status,
                    )
                    .join(AudienceSegment, AudienceSegment.id == AudienceMembership.segment_id)
                    .join(
                        ContactIntelligence,
                        ContactIntelligence.contact_id == AudienceMembership.contact_id,
                    )
                    .outerjoin(Deal, Deal.contact_id == AudienceMembership.contact_id)
                    .where(AudienceMembership.segment_id.in_(segment_ids))
                )
            ).all()

            expired_rows = (
                await session.execute(
                    select(AudienceMembership.segment_id)
                    .where(
                        AudienceMembership.segment_id.in_(segment_ids),
                        AudienceMembership.active.is_(False),
                        AudienceMembership.evaluated_at >= window_7d,
                    )
                )
            ).all()

        by_segment: dict[int, list[tuple]] = {segment.id: [] for segment in segments}
        for membership, segment, intelligence, deal_status in rows:
            by_segment[segment.id].append((membership, segment, intelligence, deal_status))

        expired_counts: dict[int, int] = {}
        for (segment_id,) in expired_rows:
            expired_counts[segment_id] = expired_counts.get(segment_id, 0) + 1

        health_rows: list[AudienceHealthSnapshot] = []
        active_sets: dict[str, set[int]] = {}
        total_active_members = 0

        for segment in segments:
            bucket = by_segment.get(segment.id, [])
            active_rows = [
                (membership, intelligence, deal_status)
                for membership, _segment, intelligence, deal_status in bucket
                if membership.active
            ]
            active_contact_ids = {membership.contact_id for membership, _, _ in active_rows}
            active_sets[segment.slug] = active_contact_ids
            total_active_members += len(active_contact_ids)

            new_members_7d = sum(
                1
                for membership, _, _ in active_rows
                if AudienceEngine._aware(membership.created_at) >= window_7d
            )
            stale_count = sum(
                1
                for _membership, intelligence, _ in active_rows
                if self._is_stale(intelligence, now)
            )
            unknown_count = sum(
                1
                for _membership, intelligence, _ in active_rows
                if (intelligence.primary_buyer_role or "UNKNOWN") == "UNKNOWN"
                or intelligence.evidence_count < segment.minimum_evidence_count
            )
            won_count = sum(
                1 for _membership, _, deal_status in active_rows if deal_status == DealStatus.WON
            )
            exportable_count = sum(
                1
                for _membership, intelligence, _ in active_rows
                if intelligence.export_eligibility == ExportEligibility.FIRST_PARTY_ELIGIBLE
            )

            active_members = len(active_rows)
            avg_confidence = (
                round(sum(membership.confidence for membership, _, _ in active_rows) / active_members)
                if active_members
                else 0
            )
            avg_intent = (
                round(sum(intelligence.intent_strength for _, intelligence, _ in active_rows) / active_members)
                if active_members
                else 0
            )
            avg_evidence = (
                round(sum(intelligence.evidence_count for _, intelligence, _ in active_rows) / active_members)
                if active_members
                else 0
            )
            avg_sources = (
                round(sum(intelligence.source_count for _, intelligence, _ in active_rows) / active_members)
                if active_members
                else 0
            )
            stale_ratio = self._ratio(stale_count, active_members)
            unknown_ratio = self._ratio(unknown_count, active_members)
            won_rate = self._ratio(won_count, active_members) if active_members else None

            issues: list[str] = []
            status = self._resolve_status(
                segment=segment,
                active_members=active_members,
                avg_confidence=avg_confidence,
                stale_ratio=stale_ratio,
                unknown_ratio=unknown_ratio,
                exportable_count=exportable_count,
                issues=issues,
            )

            health_rows.append(
                AudienceHealthSnapshot(
                    segment_slug=segment.slug,
                    segment_name=segment.name,
                    segment_status=segment.status,
                    audience_level=segment.audience_level,
                    status=status,
                    active_members=active_members,
                    new_members_7d=new_members_7d,
                    expired_7d=expired_counts.get(segment.id, 0),
                    avg_confidence=avg_confidence,
                    avg_intent_score=avg_intent,
                    avg_evidence_count=avg_evidence,
                    avg_source_count=avg_sources,
                    stale_ratio=stale_ratio,
                    unknown_ratio=unknown_ratio,
                    won_count=won_count,
                    won_rate=won_rate,
                    exportable_count=exportable_count,
                    issues=tuple(issues),
                )
            )

        overlap_rows = self._overlap_rows(segments, active_sets)
        healthy_count = sum(1 for row in health_rows if row.status == "HEALTHY")
        needs_review_count = sum(
            1 for row in health_rows if row.status in {"NEEDS_REVIEW", "NOT_EXPORTABLE", "NOISY"}
        )

        return AudienceQualityPageSnapshot(
            generated_at=now,
            vertical=selected_vertical.value,
            health_rows=tuple(health_rows),
            overlap_rows=overlap_rows,
            total_active_members=total_active_members,
            healthy_count=healthy_count,
            needs_review_count=needs_review_count,
        )

    @staticmethod
    def _is_stale(intelligence: ContactIntelligence, now: datetime) -> bool:
        last_seen = intelligence.last_seen_at
        if last_seen is None:
            return True
        if last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=UTC)
        age_days = (now - last_seen).total_seconds() / 86400
        return age_days > _STALE_DAYS

    @staticmethod
    def _ratio(numerator: int, denominator: int) -> Decimal:
        if denominator <= 0:
            return Decimal("0.00")
        return (Decimal(numerator) / Decimal(denominator) * Decimal("100")).quantize(
            _RATIO_QUANT,
            rounding=ROUND_HALF_UP,
        )

    @classmethod
    def _resolve_status(
        cls,
        *,
        segment: AudienceSegment,
        active_members: int,
        avg_confidence: int,
        stale_ratio: Decimal,
        unknown_ratio: Decimal,
        exportable_count: int,
        issues: list[str],
    ) -> str:
        if active_members == 0:
            issues.append("Нет активных участников")
            return "LOW_DATA"
        if active_members < _LOW_DATA_THRESHOLD:
            issues.append(f"Мало участников: {active_members} < {_LOW_DATA_THRESHOLD}")
            return "LOW_DATA"
        if segment.audience_level == "EXPERIMENTAL":
            issues.append("Экспериментальная аудитория требует ручной проверки")
            return "NEEDS_REVIEW"
        if stale_ratio >= _STALE_RATIO_THRESHOLD * Decimal("100"):
            issues.append(f"Высокая доля устаревших: {stale_ratio}%")
            return "STALE"
        if avg_confidence < _NOISY_CONFIDENCE or unknown_ratio >= _UNKNOWN_RATIO_THRESHOLD * Decimal(
            "100"
        ):
            if avg_confidence < _NOISY_CONFIDENCE:
                issues.append(f"Низкая средняя уверенность: {avg_confidence}")
            if unknown_ratio >= _UNKNOWN_RATIO_THRESHOLD * Decimal("100"):
                issues.append(f"Много неизвестных ролей/доказательств: {unknown_ratio}%")
            return "NOISY"
        if segment.meta_use_case != "ANALYSIS_ONLY" and exportable_count == 0:
            issues.append("Нет first-party exportable контактов для кампании")
            return "NOT_EXPORTABLE"
        if avg_confidence >= _MIN_HEALTHY_CONFIDENCE and stale_ratio < _STALE_RATIO_THRESHOLD * Decimal(
            "100"
        ):
            return "HEALTHY"
        issues.append("Смешанные сигналы качества — нужна проверка")
        return "NEEDS_REVIEW"

    @staticmethod
    def _overlap_rows(
        segments: list[AudienceSegment],
        active_sets: dict[str, set[int]],
    ) -> tuple[AudienceOverlapRow, ...]:
        rows: list[AudienceOverlapRow] = []
        for left, right in combinations(segments, 2):
            left_ids = active_sets.get(left.slug, set())
            right_ids = active_sets.get(right.slug, set())
            intersection = len(left_ids & right_ids)
            if intersection == 0:
                continue
            union = len(left_ids | right_ids)
            jaccard = (
                Decimal(intersection) / Decimal(union) * Decimal("100")
            ).quantize(_RATIO_QUANT, rounding=ROUND_HALF_UP)
            rows.append(
                AudienceOverlapRow(
                    left_slug=left.slug,
                    left_name=left.name,
                    right_slug=right.slug,
                    right_name=right.name,
                    intersection=intersection,
                    left_only=len(left_ids - right_ids),
                    right_only=len(right_ids - left_ids),
                    jaccard=jaccard,
                )
            )
        rows.sort(key=lambda item: (item.intersection, item.jaccard), reverse=True)
        return tuple(rows[:30])
