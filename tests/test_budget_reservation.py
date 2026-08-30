import asyncio
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.db.models import ExternalBudgetReservation, ExternalUsage, ReservationStatus
from app.services.usage_service import ExternalBudgetExceeded, ExternalUsageService


@pytest.mark.asyncio
async def test_budget_reservation_atomic_limits(session_factory):
    usage_svc = ExternalUsageService(session_factory)
    limit = 5

    # 1. First 5 reservations succeed
    res_ids = []
    for _ in range(5):
        rid = await usage_svc.reserve_budget("openai", "lead_analysis", limit, units=1)
        res_ids.append(rid)

    assert len(res_ids) == 5

    # 2. 6th reservation must fail
    with pytest.raises(ExternalBudgetExceeded) as exc_info:
        await usage_svc.reserve_budget("openai", "lead_analysis", limit, units=1)
    assert "Дневной лимит openai исчерпан" in str(exc_info.value)

    # 3. Releasing one reservation allows a new one
    await usage_svc.release_reservation(res_ids[0])
    new_rid = await usage_svc.reserve_budget("openai", "lead_analysis", limit, units=1)
    assert new_rid > 0

    # 4. Finalizing reservation transitions to ExternalUsage
    await usage_svc.finalize_reservation(new_rid, units=1, success=True)
    used = await usage_svc.used_today("openai")
    assert used == 1


@pytest.mark.asyncio
async def test_budget_reservation_concurrent_race(file_session_factory):
    first = ExternalUsageService(file_session_factory)
    second = ExternalUsageService(file_session_factory)
    limit = 10

    # 20 concurrent reservation attempts against limit=10
    async def try_reserve(usage_svc):
        try:
            return await usage_svc.reserve_budget("openai", "lead_analysis", limit, units=1)
        except ExternalBudgetExceeded:
            return None

    results = await asyncio.gather(
        *[try_reserve(first if index % 2 else second) for index in range(20)]
    )
    successful = [r for r in results if r is not None]
    assert len(successful) <= 10


@pytest.mark.asyncio
async def test_finalize_reservation_is_exactly_once(session_factory):
    usage = ExternalUsageService(session_factory)
    reservation_id = await usage.reserve_budget(
        "openai",
        "lead_analysis",
        10,
        reservation_key="test:exactly-once",
    )
    await usage.mark_call_started(reservation_id)
    await usage.finalize_reservation(reservation_id, details={"result": "ok"})
    await usage.finalize_reservation(reservation_id, details={"result": "duplicate"})

    async with session_factory() as session:
        count = await session.scalar(select(func.count(ExternalUsage.id)))
        reservation = await session.get(ExternalBudgetReservation, reservation_id)
    assert count == 1
    assert reservation is not None
    assert reservation.status == ReservationStatus.FINALIZED


@pytest.mark.asyncio
async def test_started_reservation_cannot_be_released_and_uncertain_still_consumes_budget(
    session_factory,
):
    usage = ExternalUsageService(session_factory)
    reservation_id = await usage.reserve_budget(
        "instagram",
        "get_reels",
        1,
        reservation_key="test:started-uncertain",
    )
    await usage.mark_call_started(reservation_id)
    await usage.release_reservation(reservation_id)

    async with session_factory() as session:
        started = await session.get(ExternalBudgetReservation, reservation_id)
    assert started is not None and started.status == ReservationStatus.RESERVED

    await usage.mark_reservation_uncertain(
        reservation_id,
        details={"billing_state": "UNKNOWN", "requires_reconciliation": True},
    )
    assert await usage.active_reservations_today("instagram") == 1
    with pytest.raises(ExternalBudgetExceeded):
        await usage.reserve_budget("instagram", "get_reels", 1)


@pytest.mark.asyncio
async def test_provider_confirmed_charge_over_reservation_is_recorded_truthfully(
    session_factory,
):
    usage = ExternalUsageService(session_factory)
    reservation_id = await usage.reserve_budget(
        "instagram",
        "get_reels",
        10,
        units=1,
        provider="scrapecreators",
    )
    await usage.mark_call_started(reservation_id)
    await usage.finalize_reservation(
        reservation_id,
        units=2,
        unit_source="PROVIDER_CONFIRMED",
    )

    async with session_factory() as session:
        reservation = await session.get(ExternalBudgetReservation, reservation_id)
        recorded = await session.scalar(select(ExternalUsage))
    assert reservation is not None
    assert reservation.actual_units == 2
    assert reservation.details_json["reservation_discrepancy"][
        "actual_exceeded_reservation"
    ] is True
    assert recorded is not None
    assert recorded.units == 2
    assert recorded.unit_source == "PROVIDER_CONFIRMED"


@pytest.mark.asyncio
async def test_expired_budget_reservation_is_reclaimed(session_factory):
    usage_svc = ExternalUsageService(session_factory)
    expired_id = await usage_svc.reserve_budget("openai", "lead_analysis", 1, lease_seconds=1)
    async with session_factory() as session:
        reservation = await session.get(ExternalBudgetReservation, expired_id)
        assert reservation is not None
        reservation.expires_at = reservation.created_at
        await session.commit()

    replacement_id = await usage_svc.reserve_budget("openai", "lead_analysis", 1)

    assert replacement_id != expired_id
    async with session_factory() as session:
        expired = await session.get(ExternalBudgetReservation, expired_id)
        assert expired is not None
        assert expired.status == ReservationStatus.EXPIRED


def test_cost_preview_estimation():
    preview = ExternalUsageService.preview_cost("followers_scan", 1000)
    assert preview.estimated_records == 1000
    assert preview.estimated_units == 20
    assert preview.estimated_cost_usd_min > Decimal("0")
    assert preview.estimated_cost_usd_max >= preview.estimated_cost_usd_min
