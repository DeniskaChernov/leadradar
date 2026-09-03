"""Controlled pilot preflight / arm / freshness / missing-policy safety."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from app.config import Settings
from app.db.models import (
    Competitor,
    ExternalBudgetReservation,
    ExternalUsage,
    OperationalControl,
    Post,
    ProviderBudgetPolicy,
)
from app.providers.budgeted import BudgetedInstagramProvider, LiveCallsDisabledError, ScanBudget
from app.schemas.instagram import InstagramProfile
from app.services.competitor_freshness_service import (
    FRESHNESS_ACTIVE,
    FRESHNESS_INACTIVE,
    FRESHNESS_STALE,
    FRESHNESS_UNKNOWN,
    CompetitorFreshnessService,
)
from app.services.deployment_readiness_service import OfflineReadinessState
from app.services.pilot_readiness_service import PilotReadinessResult, PilotReadinessService
from app.services.usage_service import ExternalUsageService


def _offline_ok(**changes) -> OfflineReadinessState:
    values = {
        "database_healthy": True,
        "database_error": None,
        "migration_at_head": True,
        "migration_drift_free": True,
        "migration_error": None,
        "backup_present": True,
        "uncertain_reservations": 0,
    }
    values.update(changes)
    return OfflineReadinessState(**values)


def _pilot_settings(**changes) -> Settings:
    values = {
        "monitor_schedule_enabled": False,
        "instagram_manual_live_scan_only": True,
        "meta_ads_live_calls_enabled": False,
        "instagram_live_calls_enabled": False,
        "external_kill_switch": True,
        "ai_mode": "rules",
        "telegram_manager_chat_ids": [1001],
        "telegram_admin_chat_ids": [9001],
    }
    values.update(changes)
    return Settings(_env_file=None, **values)


async def _seed_policy(session_factory, *, active: bool = True) -> None:
    async with session_factory() as session:
        session.add(
            ProviderBudgetPolicy(
                provider="scrapecreators",
                service="instagram",
                monthly_target_units=3000,
                monthly_soft_limit_units=3500,
                monthly_hard_limit_units=3800,
                default_scan_budget_units=5,
                maximum_manual_scan_budget_units=50,
                target_minimum_months=6,
                comments_target_units=2400,
                discovery_target_units=600,
                enrichment_target_units=200,
                reserve_target_units=600,
                active=active,
            )
        )
        await session.commit()


async def _seed_competitor(
    session_factory,
    handle: str,
    *,
    active: bool = False,
    published_days_ago: int | None = 1,
) -> Competitor:
    async with session_factory() as session:
        competitor = Competitor(
            handle=handle,
            normalized_handle=handle.strip().lower().lstrip("@"),
            active=active,
            freshness_status=FRESHNESS_UNKNOWN,
        )
        session.add(competitor)
        await session.flush()
        if published_days_ago is not None:
            session.add(
                Post(
                    competitor_id=competitor.id,
                    platform="instagram",
                    platform_post_id=f"{handle}-post",
                    url=f"https://instagram.com/p/{handle}",
                    published_at=datetime.now(UTC) - timedelta(days=published_days_ago),
                )
            )
        await session.commit()
        await session.refresh(competitor)
        return competitor


@pytest.mark.asyncio
async def test_prepare_fails_when_budget_policy_missing(session_factory):
    await _seed_competitor(session_factory, "pilot.uz", published_days_ago=1)
    await CompetitorFreshnessService(session_factory).refresh_handle("pilot.uz")
    result = await PilotReadinessService(session_factory, _pilot_settings()).evaluate(
        competitor_handle="pilot.uz",
        scan_credits=5,
        offline=_offline_ok(),
    )
    assert result.ready is False
    assert any("ProviderBudgetPolicy missing" in item for item in result.blocking_reasons)


@pytest.mark.asyncio
async def test_preflight_blockers_for_unsafe_pilot_conditions(session_factory):
    await _seed_policy(session_factory)
    await _seed_competitor(session_factory, "pilot.uz", published_days_ago=1)
    await CompetitorFreshnessService(session_factory).refresh_handle("pilot.uz")

    async with session_factory() as session:
        policy = await session.scalar(select(ProviderBudgetPolicy))
        assert policy is not None
        policy.active = False
        await session.commit()
    blocked = await PilotReadinessService(session_factory, _pilot_settings()).evaluate(
        competitor_handle="pilot.uz", scan_credits=5, offline=_offline_ok()
    )
    assert blocked.ready is False
    assert any(
        "Wallet snapshot" in item or "ProviderBudgetPolicy" in item
        for item in blocked.blocking_reasons
    )

    async with session_factory() as session:
        policy = await session.scalar(select(ProviderBudgetPolicy))
        assert policy is not None
        policy.active = True
        await session.commit()

    cases = [
        (_pilot_settings(monitor_schedule_enabled=True), "MONITOR_SCHEDULE_ENABLED", 5, None),
        (
            _pilot_settings(instagram_manual_live_scan_only=False),
            "INSTAGRAM_MANUAL_LIVE_SCAN_ONLY",
            5,
            None,
        ),
        (_pilot_settings(meta_ads_live_calls_enabled=True), "Meta live", 5, None),
        (_pilot_settings(), "Scan cap", 11, None),
        (_pilot_settings(), "freshness not approved", 5, 45),
        (_pilot_settings(), "freshness not approved", 5, 200),
    ]
    for settings, needle, credits, days in cases:
        if days is not None:
            handle = f"stale{days}.uz"
            await _seed_competitor(session_factory, handle, published_days_ago=days)
        else:
            handle = "pilot.uz"
        result = await PilotReadinessService(session_factory, settings).evaluate(
            competitor_handle=handle,
            scan_credits=credits,
            offline=_offline_ok(),
        )
        assert result.ready is False, needle
        assert any(needle in item for item in result.blocking_reasons), (
            needle,
            result.blocking_reasons,
        )

    result = await PilotReadinessService(session_factory, _pilot_settings()).evaluate(
        competitor_handle="pilot.uz",
        scan_credits=5,
        offline=_offline_ok(uncertain_reservations=2),
    )
    assert result.ready is False
    assert any("UNCERTAIN" in item for item in result.blocking_reasons)

    await _seed_competitor(session_factory, "other.uz", active=True, published_days_ago=1)
    async with session_factory() as session:
        row = await session.scalar(
            select(Competitor).where(Competitor.normalized_handle == "pilot.uz")
        )
        assert row is not None
        row.active = True
        await session.commit()
    result = await PilotReadinessService(session_factory, _pilot_settings()).evaluate(
        competitor_handle="pilot.uz",
        scan_credits=5,
        offline=_offline_ok(),
        require_single_active=True,
    )
    assert result.ready is False
    assert any("ровно 1" in item for item in result.blocking_reasons)


@pytest.mark.asyncio
async def test_preflight_requires_manager_chat_and_warns_when_same_as_admin(session_factory):
    await _seed_policy(session_factory)
    await _seed_competitor(session_factory, "pilot.uz", published_days_ago=1)
    await CompetitorFreshnessService(session_factory).refresh_handle("pilot.uz")

    missing = await PilotReadinessService(
        session_factory, _pilot_settings(telegram_manager_chat_ids=[])
    ).evaluate(competitor_handle="pilot.uz", scan_credits=5, offline=_offline_ok())
    assert missing.ready is False
    assert any("TELEGRAM_MANAGER_CHAT_IDS" in item for item in missing.blocking_reasons)

    shared = await PilotReadinessService(
        session_factory,
        _pilot_settings(telegram_manager_chat_ids=[9001], telegram_admin_chat_ids=[9001]),
    ).evaluate(competitor_handle="pilot.uz", scan_credits=5, offline=_offline_ok())
    assert shared.ready is True
    assert any("совпадает с ADMIN" in item for item in shared.warnings)


@pytest.mark.asyncio
async def test_arm_does_not_mutate_when_preflight_fails(session_factory, monkeypatch):
    await _seed_competitor(session_factory, "pilot.uz", active=False, published_days_ago=1)
    from scripts import arm_controlled_pilot as arm_mod

    async def _fail_eval(self, **kwargs):
        return PilotReadinessResult(
            ready=False,
            blocking_reasons=("Active ProviderBudgetPolicy missing",),
            warnings=(),
            snapshot={},
        )

    monkeypatch.setattr(arm_mod, "get_settings", lambda: _pilot_settings())
    monkeypatch.setattr(
        arm_mod,
        "create_engine",
        lambda settings: type("E", (), {"dispose": AsyncMock()})(),
    )
    monkeypatch.setattr(arm_mod, "create_session_factory", lambda engine: session_factory)
    monkeypatch.setattr(arm_mod.PilotReadinessService, "evaluate", _fail_eval)

    code = await arm_mod.arm(competitor="pilot.uz", credits=5)
    assert code == 1
    async with session_factory() as session:
        active = list(
            await session.scalars(select(Competitor).where(Competitor.active.is_(True)))
        )
        ops = await session.get(OperationalControl, 1)
    assert active == []
    assert ops is None or ops.radar_live_armed is False


@pytest.mark.asyncio
async def test_arm_enables_radar_only_exactly_one_competitor_no_openai(
    session_factory, monkeypatch
):
    await _seed_policy(session_factory)
    await _seed_competitor(session_factory, "keep.uz", active=True, published_days_ago=1)
    await _seed_competitor(session_factory, "pause.uz", active=True, published_days_ago=1)

    from scripts import arm_controlled_pilot as arm_mod

    async def _pass_eval(self, **kwargs):
        return PilotReadinessResult(
            ready=True,
            blocking_reasons=(),
            warnings=(),
            snapshot={"competitor": "keep.uz"},
        )

    monkeypatch.setattr(arm_mod, "get_settings", lambda: _pilot_settings(web_manager_id=1))
    monkeypatch.setattr(
        arm_mod,
        "create_engine",
        lambda settings: type("E", (), {"dispose": AsyncMock()})(),
    )
    monkeypatch.setattr(arm_mod, "create_session_factory", lambda engine: session_factory)
    monkeypatch.setattr(arm_mod.PilotReadinessService, "evaluate", _pass_eval)

    code = await arm_mod.arm(competitor="keep.uz", credits=5)
    assert code == 0

    async with session_factory() as session:
        active = list(
            await session.scalars(
                select(Competitor.normalized_handle).where(Competitor.active.is_(True))
            )
        )
        ops = await session.get(OperationalControl, 1)
    assert active == ["keep.uz"]
    assert ops is not None
    assert ops.radar_live_armed is True
    assert ops.openai_live_armed is False
    assert ops.default_scan_credits == 5


@pytest.mark.asyncio
async def test_missing_provider_budget_policy_blocks_before_network(session_factory):
    usage = ExternalUsageService(session_factory)
    calls = {"n": 0}

    class CountingProvider:
        name = "scrapecreators"

        def begin_cycle(self) -> None:
            return None

        def pop_credit_observations(self):
            return []

        async def get_profile(self, handle: str) -> InstagramProfile:
            calls["n"] += 1
            return InstagramProfile(
                username=handle,
                profile_url=f"https://instagram.com/{handle}",
            )

        async def get_reels(self, handle: str):
            calls["n"] += 1
            return []

        async def get_post(self, url: str, competitor: str):
            calls["n"] += 1
            raise AssertionError("should not run")

        async def get_comments(self, post):
            calls["n"] += 1
            raise AssertionError("should not run")

        async def aclose(self) -> None:
            return None

    provider = BudgetedInstagramProvider(
        CountingProvider(),
        usage,
        enabled=True,
        daily_limit=100,
        scan_budget=ScanBudget(default_limit=10),
    )
    with pytest.raises(LiveCallsDisabledError, match="ProviderBudgetPolicy missing"):
        await provider.get_profile("pilot.uz")

    assert calls["n"] == 0
    async with session_factory() as session:
        reservations = await session.scalar(
            select(func.count()).select_from(ExternalBudgetReservation)
        )
        spends = await session.scalar(select(func.count()).select_from(ExternalUsage))
    assert int(reservations or 0) == 0
    assert int(spends or 0) == 0


@pytest.mark.asyncio
async def test_freshness_classify_and_manual_confirm(session_factory):
    svc = CompetitorFreshnessService(session_factory)
    assert svc.classify(None).status == FRESHNESS_UNKNOWN
    now = datetime.now(UTC)
    assert svc.classify(now - timedelta(days=1)).status == FRESHNESS_ACTIVE
    assert svc.classify(now - timedelta(days=45)).status == FRESHNESS_STALE
    assert svc.classify(now - timedelta(days=200)).status == FRESHNESS_INACTIVE

    await _seed_competitor(session_factory, "old.uz", published_days_ago=200)
    competitor = await svc.refresh_handle("old.uz")
    assert competitor.freshness_status == FRESHNESS_INACTIVE
    assert CompetitorFreshnessService.is_pilot_approved(competitor) is False
    confirmed = await svc.confirm_for_pilot("old.uz", manager_id=7)
    assert CompetitorFreshnessService.is_pilot_approved(confirmed) is True
    assert confirmed.manual_freshness_confirmed_at is not None


@pytest.mark.asyncio
async def test_prepare_script_exit_nonzero_on_blockers(session_factory, monkeypatch):
    from scripts import prepare_controlled_pilot as prep

    async def _fail_eval(self, **kwargs):
        return PilotReadinessResult(
            ready=False,
            blocking_reasons=("Active ProviderBudgetPolicy missing",),
            warnings=(),
            snapshot={
                "offline_ready": True,
                "backup_present": True,
                "uncertain_reservations": 0,
                "policy_present": False,
                "wallet_present": False,
                "monthly_remaining": None,
                "credits_remaining": None,
                "credits_remaining_source": None,
                "monitor_schedule_enabled": False,
                "instagram_manual_live_scan_only": True,
                "meta_ads_live_enabled": False,
                "freshness_status": None,
                "active_handles": [],
            },
        )

    monkeypatch.setattr(prep, "get_settings", lambda: _pilot_settings())
    monkeypatch.setattr(
        prep,
        "create_engine",
        lambda settings: type("E", (), {"dispose": AsyncMock()})(),
    )
    monkeypatch.setattr(prep, "create_session_factory", lambda engine: session_factory)
    monkeypatch.setattr(prep.PilotReadinessService, "evaluate", _fail_eval)

    code = await prep._run("missing.uz", 5)
    assert code == 1


def test_arm_module_cli_defaults():
    from scripts import arm_controlled_pilot

    assert callable(arm_controlled_pilot.main)
    assert arm_controlled_pilot.DEFAULT_CREDITS == 5
    assert not hasattr(arm_controlled_pilot, "PILOT_HANDLE")


def test_restore_and_flush_modules_still_expose_main():
    from scripts import flush_openai_pending, restore_pilot_competitors

    assert callable(restore_pilot_competitors.main)
    assert restore_pilot_competitors.RESTORE_TIERS == ("A", "B", "C")
    assert callable(flush_openai_pending.main)
