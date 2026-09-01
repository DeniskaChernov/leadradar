from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.db.models import Competitor
from app.services.adaptive_monitoring_policy import (
    AdaptiveMonitoringPolicy,
    CompetitorMonitoringFacts,
)
from app.services.adaptive_monitoring_service import AdaptiveMonitoringService


def _facts(now: datetime, **changes) -> CompetitorMonitoringFacts:
    values = {
        "competitor_id": 1,
        "handle": "aiko.uz",
        "tier": "A",
        "last_scanned_at": now - timedelta(hours=10),
        "newest_reel_at": None,
        "last_commercial_at": None,
        "last_hot_at": None,
        "last_b2b_at": None,
        "commercial_signals_30d": 0,
        "scan_error_count": 0,
    }
    values.update(changes)
    return CompetitorMonitoringFacts(**values)


def test_adaptive_policy_assigns_four_states_and_expected_intervals():
    now = datetime(2026, 8, 31, tzinfo=UTC)
    active = AdaptiveMonitoringPolicy.decide(
        _facts(now, newest_reel_at=now - timedelta(hours=12)),
        now=now,
    )
    warm = AdaptiveMonitoringPolicy.decide(
        _facts(now, last_commercial_at=now - timedelta(days=2)),
        now=now,
    )
    cold = AdaptiveMonitoringPolicy.decide(
        _facts(now, last_commercial_at=now - timedelta(days=8)),
        now=now,
    )
    dormant = AdaptiveMonitoringPolicy.decide(_facts(now), now=now)

    assert (active.state, active.interval_hours) == ("ACTIVE", 4)
    assert (warm.state, warm.interval_hours) == ("WARM", 12)
    assert (cold.state, cold.interval_hours) == ("COLD", 48)
    assert (dormant.state, dormant.interval_hours) == ("DORMANT", 72)
    assert active.priority_score > warm.priority_score > cold.priority_score
    assert cold.priority_score > dormant.priority_score


async def test_due_scheduling_persists_state_and_manual_force_only_changes_selection(
    session_factory,
):
    now = datetime.now(UTC)
    async with session_factory() as session:
        session.add(
            Competitor(
                handle="quiet.uz",
                normalized_handle="quiet.uz",
                tier="B",
                active=True,
                last_scanned_at=now,
            )
        )
        await session.commit()
    service = AdaptiveMonitoringService(session_factory, hot_threshold=70)

    scheduled, not_due = await service.ranked_due_competitors([], force=False)
    forced, forced_not_due = await service.ranked_due_competitors([], force=True)

    assert scheduled == []
    assert not_due == 1
    assert len(forced) == 1
    assert forced_not_due == 0
    async with session_factory() as session:
        competitor = await session.scalar(select(Competitor))
    assert competitor is not None
    assert competitor.monitoring_state == "DORMANT"
    assert competitor.next_scan_at is not None
    assert competitor.adaptive_policy_version == AdaptiveMonitoringPolicy.VERSION
