from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, or_, true
from sqlalchemy.sql.elements import ColumnElement

from app.db.models import Comment


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def signal_observed_at(
    *,
    created_at_platform: datetime | None,
    discovered_at: datetime | None = None,
) -> datetime | None:
    if created_at_platform is not None:
        return _ensure_utc(created_at_platform)
    if discovered_at is not None:
        return _ensure_utc(discovered_at)
    return None


def signal_age_cutoff(*, max_age_days: int, now: datetime | None = None) -> datetime:
    reference = now or datetime.now(UTC)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=UTC)
    return reference - timedelta(days=max_age_days)


def is_signal_within_window(
    observed_at: datetime | None,
    *,
    max_age_days: int,
    now: datetime | None = None,
) -> bool:
    """True — сигнал достаточно свежий для анализа и live-ленты."""
    if max_age_days <= 0:
        return True
    if observed_at is None:
        # Провайдер иногда не отдаёт timestamp; не отбрасываем такие комментарии.
        return True
    return _ensure_utc(observed_at) >= signal_age_cutoff(max_age_days=max_age_days, now=now)


def fresh_signal_clause(
    *,
    max_age_days: int,
    now: datetime | None = None,
) -> ColumnElement[bool]:
    """SQLAlchemy-фильтр: комментарий в окне свежести."""
    if max_age_days <= 0:
        return true()
    cutoff = signal_age_cutoff(max_age_days=max_age_days, now=now)
    return or_(
        and_(
            Comment.created_at_platform.is_not(None),
            Comment.created_at_platform >= cutoff,
        ),
        and_(
            Comment.created_at_platform.is_(None),
            Comment.discovered_at >= cutoff,
        ),
    )
