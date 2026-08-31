"""Hardening: ScanBudget cycle limits and uncertain external failures."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db.models import ExternalBudgetReservation, ReservationStatus
from app.providers.base import ProviderCallUncertainError
from app.providers.budgeted import BudgetedInstagramProvider, ScanBudget
from app.schemas.instagram import InstagramProfile, ProviderCreditObservation
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


class ChargedThenBoomProvider:
    name = "scrapecreators"

    def __init__(self) -> None:
        self.calls = 0
        self._credit_observations = []

    def begin_cycle(self) -> None:
        return None

    def pop_credit_observations(self):
        items = self._credit_observations
        self._credit_observations = []
        return items

    async def get_profile(self, handle: str) -> InstagramProfile:
        self.calls += 1
        self._credit_observations.append(
            ProviderCreditObservation(
                idempotency_key=f"profile-{self.calls}",
                provider="scrapecreators",
                operation="get_profile",
                credits_charged=1,
                credits_remaining=10,
            )
        )
        if self.calls == 1:
            raise RuntimeError("parse fail after billed response")
        return InstagramProfile(username=handle, profile_url=f"https://instagram.com/{handle}")

    async def get_reels(self, handle: str):
        raise RuntimeError("unused")

    async def get_post(self, url: str, competitor: str):
        raise RuntimeError("unused")

    async def get_comments(self, post):
        raise RuntimeError("unused")

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
async def test_billed_parse_failure_does_not_leak_credits_to_next_call(session_factory):
    usage = ExternalUsageService(session_factory)
    provider = BudgetedInstagramProvider(
        ChargedThenBoomProvider(),
        usage,
        enabled=True,
        daily_limit=100,
        scan_budget=ScanBudget(default_limit=10),
    )

    with pytest.raises(ProviderCallUncertainError):
        await provider.get_profile("aiko.uz")

    profile = await provider.get_profile("aiko.uz")
    assert profile.username == "aiko.uz"

    async with session_factory() as session:
        reservations = list(await session.scalars(select(ExternalBudgetReservation)))
    assert len(reservations) == 2
    assert {item.status for item in reservations} == {ReservationStatus.FINALIZED}
    assert sum(item.actual_units or 0 for item in reservations) == 2
