from datetime import UTC, datetime, timedelta

from app.services.signal_recency import (
    fresh_signal_clause,
    is_signal_within_window,
    signal_age_cutoff,
    signal_observed_at,
)


def test_signal_within_window_respects_max_age():
    now = datetime(2026, 3, 1, tzinfo=UTC)
    fresh = now - timedelta(days=10)
    stale = now - timedelta(days=45)
    assert is_signal_within_window(fresh, max_age_days=30, now=now)
    assert not is_signal_within_window(stale, max_age_days=30, now=now)


def test_signal_without_platform_date_is_allowed():
    now = datetime(2026, 3, 1, tzinfo=UTC)
    assert is_signal_within_window(None, max_age_days=30, now=now)


def test_signal_observed_at_prefers_platform_date():
    platform = datetime(2026, 1, 1, tzinfo=UTC)
    discovered = datetime(2026, 2, 1, tzinfo=UTC)
    assert signal_observed_at(
        created_at_platform=platform,
        discovered_at=discovered,
    ) == platform


def test_fresh_signal_clause_disabled_when_max_age_zero():
    clause = fresh_signal_clause(max_age_days=0)
    assert clause is not None


def test_signal_age_cutoff():
    now = datetime(2026, 3, 31, tzinfo=UTC)
    assert signal_age_cutoff(max_age_days=30, now=now) == datetime(2026, 3, 1, tzinfo=UTC)
