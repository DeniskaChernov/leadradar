from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.db.models import (
    Comment,
    Contact,
    ExternalBudgetReservation,
    ExternalUsage,
    Lead,
    ProviderCreditSnapshot,
)
from app.providers.base import InstagramProvider, ProviderCallUncertainError, ProviderError
from app.providers.budgeted import BudgetedInstagramProvider, ScanBudgetExceededError
from app.providers.fallback import FallbackInstagramProvider
from app.providers.replay import ReplayInstagramProvider
from app.schemas.instagram import (
    InstagramComment,
    InstagramPost,
    InstagramProfile,
    ProviderCreditObservation,
)
from app.services.ai_service import HybridLeadAnalyzer, RuleBasedLeadAnalyzer
from app.services.contact_service import ContactService
from app.services.instagram_monitor import InstagramMonitor
from app.services.lead_service import LeadService
from app.services.usage_service import ExternalUsageService


class NullNotifier:
    async def notify_hot_lead(self, lead_id: int) -> int:
        return 0

    async def flush_pending(self) -> int:
        return 0


async def test_replay_scenario_creates_new_lead_without_external_calls(session_factory, tmp_path):
    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "replay_aiko.json"
    provider = ReplayInstagramProvider(fixture, tmp_path / "state.json")
    analyzer = HybridLeadAnalyzer(RuleBasedLeadAnalyzer(), None, mode="rules")
    monitor = InstagramMonitor(
        session_factory=session_factory,
        provider=provider,
        contact_service=ContactService(session_factory),
        lead_service=LeadService(session_factory, analyzer, 70),
        notifier=NullNotifier(),
        competitors=["aiko.uz"],
        process_existing_comments=False,
    )

    baseline = await monitor.run_cycle()
    assert baseline.comments_created == 3
    assert baseline.leads_created == 0

    status = provider.scenario.advance()
    assert status.step == 1
    second = await monitor.run_cycle()

    assert second.comments_created == 1
    assert second.leads_created == 1
    async with session_factory() as session:
        assert await session.scalar(select(func.count(Contact.id))) == 4
        assert await session.scalar(select(func.count(Comment.id))) == 4
        lead = await session.scalar(select(Lead))
        assert lead is not None
        assert lead.lead_score >= 70
        assert lead.ai_source == "local_rules"


class StubProfileProvider(InstagramProvider):
    def __init__(self, name: str, fail: bool) -> None:
        self.name = name
        self.fail = fail

    async def get_profile(self, handle: str) -> InstagramProfile:
        if self.fail:
            raise ProviderError("temporary")
        return InstagramProfile(username=handle, profile_url=f"https://instagram.com/{handle}/")

    async def get_reels(self, handle: str) -> list[InstagramPost]:
        raise NotImplementedError

    async def get_post(self, url: str, competitor: str) -> InstagramPost:
        raise NotImplementedError

    async def get_comments(self, post: InstagramPost) -> list[InstagramComment]:
        raise NotImplementedError


class CreditAwareProfileProvider(StubProfileProvider):
    def __init__(self) -> None:
        super().__init__("scrapecreators", False)
        self._observations = [
            ProviderCreditObservation(
                idempotency_key="provider-response:credit-aware",
                provider="scrapecreators",
                operation="get_profile",
                credits_remaining=21_840,
                credits_charged=2,
            )
        ]

    def pop_credit_observations(self) -> list[ProviderCreditObservation]:
        observations = self._observations
        self._observations = []
        return observations


@pytest.mark.asyncio
async def test_fallback_blocked_after_uncertain_primary_call(session_factory):
    from sqlalchemy import select

    from app.db.models import ExternalBudgetReservation, ReservationStatus
    from tests.conftest import seed_scrapecreators_instagram_policy

    await seed_scrapecreators_instagram_policy(session_factory)
    usage = ExternalUsageService(session_factory)
    primary = BudgetedInstagramProvider(
        StubProfileProvider("scrapecreators", True), usage, enabled=True, daily_limit=10
    )
    fallback = BudgetedInstagramProvider(
        StubProfileProvider("brightdata", False), usage, enabled=True, daily_limit=10
    )
    provider = FallbackInstagramProvider(primary, fallback)

    with pytest.raises(ProviderCallUncertainError):
        await provider.get_profile("aiko.uz")

    # Primary fail after call_started → UNCERTAIN. Fallback must not run (no double spend).
    assert await usage.used_today("instagram") == 0
    assert await usage.active_reservations_today("instagram") == 1
    breakdown = await usage.breakdown_today("instagram")
    assert breakdown == {}
    async with session_factory() as session:
        uncertain = list(
            await session.scalars(
                select(ExternalBudgetReservation).where(
                    ExternalBudgetReservation.status == ReservationStatus.UNCERTAIN
                )
            )
        )
    assert len(uncertain) == 1
    assert uncertain[0].provider == "scrapecreators"


@pytest.mark.asyncio
async def test_provider_confirmed_response_reconciles_wallet_and_actual_usage(
    session_factory,
):
    from tests.conftest import seed_scrapecreators_instagram_policy

    await seed_scrapecreators_instagram_policy(session_factory)
    usage = ExternalUsageService(session_factory)
    provider = BudgetedInstagramProvider(
        CreditAwareProfileProvider(),
        usage,
        enabled=True,
        daily_limit=10,
    )

    with pytest.raises(ScanBudgetExceededError, match="превысило резерв"):
        await provider.get_profile("aiko.uz")

    async with session_factory() as session:
        snapshot = await session.scalar(select(ProviderCreditSnapshot))
        reservation = await session.scalar(select(ExternalBudgetReservation))
        recorded = await session.scalar(select(ExternalUsage))
    assert snapshot is not None and snapshot.credits_remaining == 21_840
    assert snapshot.credits_charged == 2
    assert reservation is not None and reservation.actual_units == 2
    assert recorded is not None and recorded.units == 2
    assert recorded.unit_source == "PROVIDER_CONFIRMED"

async def test_tasks_page_renders_in_russian(session_factory):
    from httpx import ASGITransport, AsyncClient

    from app.config import Settings
    from app.services.lead_workflow_service import LeadWorkflowService
    from app.services.monitor_controller import MonitorController
    from app.web.app import build_web_app
    from app.web.queries import WebQueryService

    settings = Settings(_env_file=None, web_enabled=True)
    controller = MonitorController(monitor=None)  # type: ignore[arg-type]
    app = build_web_app(
        settings,
        WebQueryService(session_factory, hot_threshold=70),
        LeadWorkflowService(session_factory, hot_threshold=70),
        controller,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/tasks")
    assert response.status_code == 200
    assert "Задачи менеджера" in response.text or "Кому писать" in response.text
    assert "ОЧЕРЕДЬ КОНТАКТОВ" in response.text
    assert "tasks-hero" in response.text
