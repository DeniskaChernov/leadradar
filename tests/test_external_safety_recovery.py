from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.db.models import (
    AIRequest,
    AIRequestStatus,
    ExternalBudgetReservation,
    ExternalUsage,
    ReservationStatus,
)
from app.services.external_safety_recovery_service import ExternalSafetyRecoveryService
from app.services.usage_service import ExternalUsageService
from tests.test_lead_workflow import create_lead


@pytest.mark.asyncio
async def test_recovery_releases_unsent_and_counts_ambiguous_reservation(session_factory):
    usage = ExternalUsageService(session_factory)
    unsent_id = await usage.reserve_budget(
        "openai", "lead_analysis", 10, reservation_key="recovery:unsent"
    )
    ambiguous_id = await usage.reserve_budget(
        "openai", "lead_analysis", 10, reservation_key="recovery:ambiguous"
    )
    await usage.mark_call_started(ambiguous_id)
    expired_at = datetime.now(UTC) - timedelta(seconds=1)
    async with session_factory() as session:
        for reservation_id in (unsent_id, ambiguous_id):
            reservation = await session.get(ExternalBudgetReservation, reservation_id)
            assert reservation is not None
            reservation.expires_at = expired_at
        await session.commit()

    recovery = ExternalSafetyRecoveryService(
        session_factory, usage, max_ai_attempts=3
    )
    first = await recovery.recover()
    second = await recovery.recover()

    assert first.reservations_released == 1
    assert first.reservations_counted_uncertain == 1
    assert second.reservations_released == 0
    assert second.reservations_counted_uncertain == 0
    async with session_factory() as session:
        unsent = await session.get(ExternalBudgetReservation, unsent_id)
        ambiguous = await session.get(ExternalBudgetReservation, ambiguous_id)
        usage_count = await session.scalar(select(func.count(ExternalUsage.id)))
    assert unsent is not None and unsent.status == ReservationStatus.RELEASED
    assert ambiguous is not None and ambiguous.status == ReservationStatus.UNCERTAIN
    assert ambiguous.actual_units is None
    assert ambiguous.details_json["requires_reconciliation"] is True
    assert usage_count == 0


@pytest.mark.asyncio
async def test_recovery_stops_exhausted_stale_ai_claim(session_factory):
    lead_id = await create_lead(session_factory)
    async with session_factory() as session:
        session.add(
            AIRequest(
                lead_id=lead_id,
                analysis_version="3.0",
                context_fingerprint="f" * 64,
                model="gpt-5-mini",
                status=AIRequestStatus.CLAIMED,
                claim_expires_at=datetime.now(UTC) - timedelta(seconds=1),
                claim_token="stale-token",
                attempt_count=3,
            )
        )
        await session.commit()

    usage = ExternalUsageService(session_factory)
    stats = await ExternalSafetyRecoveryService(
        session_factory, usage, max_ai_attempts=3
    ).recover()

    assert stats.ai_permanent == 1
    async with session_factory() as session:
        request = await session.scalar(select(AIRequest))
    assert request is not None
    assert request.status == AIRequestStatus.PERMANENT_FAILURE
    assert request.claim_token is None
    assert request.error_type == "STALE_CLAIM"
