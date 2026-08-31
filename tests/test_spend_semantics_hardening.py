"""Hardening: ScanBudget cycle limits and uncertain external failures."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db.models import ExternalBudgetReservation, ReservationStatus
from app.providers.base import ProviderCallUncertainError
from app.providers.budgeted import BudgetedInstagramProvider, ScanBudget
from app.schemas.instagram import InstagramProfile
from app.services.usage_service import ExternalUsageService


class BoomProvider:
    name = "scrapecreators"

    def begin_cycle(self) -> None:
        return None

    def pop_credit_observations(self):
        return []

    async def get_profile(self, handle: str) -> InstagramProfile:
        raise RuntimeError("network down")

    async def get_reels(self, handle: str):
        raise RuntimeError("network down")

    async def get_post(self, url: str, competitor: str):
        raise RuntimeError("network down")

    async def get_comments(self, post):
        raise RuntimeError("network down")

    async def aclose(self) -> None:
        return None


def test_scan_budget_manual_cap_does_not_stick_after_restore():
    budget = ScanBudget(default_limit=10)
    budget.apply_cycle_limit(40)
    assert budget.limit == 40
    budget.consume(2)
    budget.restore_default_limit()
    assert budget.limit == 10
    assert budget.used == 0


def test_scan_budget_begin_cycle_keeps_manual_cap_until_restore():
    budget = ScanBudget(default_limit=10)
    budget.apply_cycle_limit(40)
    budget.reset_usage()
    assert budget.limit == 40
    budget.restore_default_limit()
    assert budget.limit == 10


@pytest.mark.asyncio
async def test_started_external_failure_marks_reservation_uncertain(session_factory):
    usage = ExternalUsageService(session_factory)
    provider = BudgetedInstagramProvider(
        BoomProvider(),
        usage,
        enabled=True,
        daily_limit=100,
        scan_budget=ScanBudget(default_limit=10),
    )

    with pytest.raises(ProviderCallUncertainError):
        await provider.get_profile("aiko.uz")

    async with session_factory() as session:
        reservation = await session.scalar(select(ExternalBudgetReservation))
    assert reservation is not None
    assert reservation.status == ReservationStatus.UNCERTAIN
    assert reservation.call_started_at is not None
    assert reservation.details_json.get("reason")
