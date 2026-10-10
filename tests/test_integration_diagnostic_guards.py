import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.config import Settings
from app.db.models import (
    ExternalBudgetReservation,
    ExternalUsage,
    ProviderBudgetPolicy,
    ReservationStatus,
)
from app.providers.mock import MockInstagramProvider
from app.services.operational_control_service import OperationalControlService
from app.services.usage_service import ExternalUsageService
from scripts import check_integrations
from tests.conftest import seed_scrapecreators_instagram_policy


@pytest_asyncio.fixture(autouse=True)
async def diagnostic_budget_policies(file_session_factory):
    await seed_scrapecreators_instagram_policy(file_session_factory)
    async with file_session_factory() as session:
        session.add(ProviderBudgetPolicy(
            provider="brightdata", service="instagram", monthly_target_units=3000,
            monthly_soft_limit_units=3500, monthly_hard_limit_units=3800,
            default_scan_budget_units=5, maximum_manual_scan_budget_units=50,
            target_minimum_months=6, comments_target_units=1, discovery_target_units=1,
            enrichment_target_units=0, reserve_target_units=1,
        ))
        await session.commit()


class DiagnosticProvider(MockInstagramProvider):
    def __init__(self, name, session_factory):
        super().__init__()
        self.name = name
        self.session_factory = session_factory
        self.calls = 0
        self.closed = False
        self.has_reservation_before_call = False
        self.failure = None

    async def get_profile(self, handle):
        self.calls += 1
        async with self.session_factory() as session:
            self.has_reservation_before_call = bool(await session.scalar(
                select(ExternalBudgetReservation.id).where(
                    ExternalBudgetReservation.provider == self.name,
                    ExternalBudgetReservation.call_started_at.is_not(None),
                    ExternalBudgetReservation.status == ReservationStatus.RESERVED,
                )
            ))
        if self.failure:
            raise self.failure
        return await super().get_profile(handle)

    async def aclose(self):
        self.closed = True


def diagnostic_setup(session_factory, monkeypatch, **overrides):
    settings = Settings(
        _env_file=None, external_kill_switch=False,
        external_live_unlock="ALLOW_EXTERNAL_CALLS", instagram_live_calls_enabled=True,
        instagram_provider="scrapecreators", scrapecreators_api_key="fake-key",
        brightdata_api_key="fake-key", competitors=["aiko.uz"],
        **overrides,
    )
    from app.providers import brightdata, scrapecreators

    primary = DiagnosticProvider("scrapecreators", session_factory)
    secondary = DiagnosticProvider("brightdata", session_factory)
    monkeypatch.setattr(scrapecreators, "ScrapeCreatorsProvider", lambda *a, **kw: primary)
    monkeypatch.setattr(brightdata, "BrightDataProvider", lambda *a, **kw: secondary)
    monkeypatch.setattr(check_integrations, "create_engine", lambda _: session_factory.kw["bind"])
    return settings, primary, secondary


async def test_live_diagnostics_respect_database_live_switch(file_session_factory, monkeypatch):
    settings, primary, secondary = diagnostic_setup(file_session_factory, monkeypatch)
    await OperationalControlService(file_session_factory).load()

    results = await check_integrations.live_checks(settings)

    assert primary.calls == secondary.calls == 0
    assert all(item.status == check_integrations.CheckStatus.SKIP for item in results)


async def test_live_diagnostics_cannot_bypass_uncertain_billing(file_session_factory, monkeypatch):
    settings, primary, secondary = diagnostic_setup(file_session_factory, monkeypatch)
    await OperationalControlService(file_session_factory).set_radar_live(True)
    usage = ExternalUsageService(file_session_factory)
    reserved = await usage.reserve_budget("instagram", "prior_call", 10, provider="scrapecreators")
    await usage.mark_call_started(reserved)
    await usage.mark_reservation_uncertain(reserved, reason="unknown provider outcome")

    results = await check_integrations.live_checks(settings)

    assert primary.calls == secondary.calls == 0
    assert all(item.status == check_integrations.CheckStatus.SKIP for item in results)
    async with file_session_factory() as session:
        assert await session.scalar(select(func.count(ExternalBudgetReservation.id))) == 1
        assert await session.scalar(select(func.count(ExternalUsage.id))) == 0


@pytest.mark.parametrize("cap,expected", [(0, 0), (1, 1), (5, 2)])
async def test_live_diagnostics_share_cap_and_persist_spend_before_request(
    file_session_factory, monkeypatch, cap, expected,
):
    settings, primary, secondary = diagnostic_setup(
        file_session_factory, monkeypatch, instagram_max_units_per_scan=cap,
    )
    await OperationalControlService(file_session_factory).set_radar_live(True)

    await check_integrations.live_checks(settings)

    assert primary.calls + secondary.calls == expected
    for provider in (primary, secondary):
        if provider.calls:
            assert provider.has_reservation_before_call
        assert provider.closed
    async with file_session_factory() as session:
        assert await session.scalar(select(func.count(ExternalUsage.id))) == expected
        reservations = list(await session.scalars(select(ExternalBudgetReservation)))
        assert len(reservations) == expected
        assert all(row.status == ReservationStatus.FINALIZED for row in reservations)


async def test_ambiguous_diagnostic_does_not_call_second_paid_provider(file_session_factory, monkeypatch):
    settings, primary, secondary = diagnostic_setup(file_session_factory, monkeypatch)
    await OperationalControlService(file_session_factory).set_radar_live(True)
    primary.failure = ConnectionError("Ambiguous provider response")

    results = await check_integrations.live_checks(settings)

    assert primary.calls == 1 and secondary.calls == 0
    assert results[0].status == check_integrations.CheckStatus.FAIL
    assert results[1].status == check_integrations.CheckStatus.SKIP
    async with file_session_factory() as session:
        reservations = list(await session.scalars(select(ExternalBudgetReservation)))
        assert len(reservations) == 1 and reservations[0].status == ReservationStatus.UNCERTAIN
