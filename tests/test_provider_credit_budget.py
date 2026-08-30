from datetime import UTC, datetime, timedelta

import pytest

from app.db.models import ProviderBudgetPolicy
from app.services.provider_credit_budget_service import ProviderCreditBudgetService
from app.services.usage_service import ExternalBudgetExceeded, ExternalUsageService


async def _add_policy(session_factory, *, hard: int = 3) -> None:
    async with session_factory() as session:
        session.add(
            ProviderBudgetPolicy(
                provider="scrapecreators",
                service="instagram",
                monthly_target_units=min(2, hard),
                monthly_soft_limit_units=min(2, hard),
                monthly_hard_limit_units=hard,
                default_scan_budget_units=1,
                maximum_manual_scan_budget_units=50,
                target_minimum_months=6,
                comments_target_units=1,
                discovery_target_units=1,
                enrichment_target_units=0,
                reserve_target_units=1,
                active=True,
            )
        )
        await session.commit()


@pytest.mark.asyncio
async def test_monthly_provider_hard_limit_is_enforced_inside_reservation(
    session_factory,
):
    await _add_policy(session_factory)
    usage = ExternalUsageService(session_factory)
    first = await usage.reserve_budget(
        "instagram",
        "get_comments",
        100,
        units=2,
        provider="scrapecreators",
    )
    await usage.finalize_reservation(first, units=2)

    with pytest.raises(ExternalBudgetExceeded, match="Месячный hard limit"):
        await usage.reserve_budget(
            "instagram",
            "get_reels",
            100,
            units=2,
            provider="scrapecreators",
        )
    final = await usage.reserve_budget(
        "instagram",
        "get_reels",
        100,
        units=1,
        provider="scrapecreators",
    )
    assert final > 0


@pytest.mark.asyncio
async def test_wallet_prefers_provider_confirmed_balance_and_is_idempotent(
    session_factory,
):
    service = ProviderCreditBudgetService(session_factory)
    now = datetime.now(UTC)
    estimated = await service.record_credit_snapshot(
        idempotency_key="wallet:estimate",
        provider="scrapecreators",
        operation="manual_import",
        source="LOCAL_ESTIMATE",
        credits_remaining=25_000,
        credits_charged=None,
        observed_at=now,
    )
    confirmed = await service.record_credit_snapshot(
        idempotency_key="wallet:confirmed",
        provider="scrapecreators",
        operation="get_reels",
        source="API_RESPONSE",
        credits_remaining=21_842,
        credits_charged=1,
        observed_at=now - timedelta(days=1),
    )
    duplicate = await service.record_credit_snapshot(
        idempotency_key="wallet:confirmed",
        provider="scrapecreators",
        operation="get_reels",
        source="API_RESPONSE",
        credits_remaining=1,
        credits_charged=99,
    )

    latest = await service.latest_balance("scrapecreators")
    assert estimated.id != confirmed.id
    assert duplicate.id == confirmed.id
    assert latest is not None
    assert latest.credits_remaining == 21_842
    assert latest.source == "API_RESPONSE"


@pytest.mark.asyncio
async def test_available_scan_is_clamped_by_month_daily_manual_and_confirmed_wallet(
    session_factory,
):
    await _add_policy(session_factory, hard=20)
    service = ProviderCreditBudgetService(session_factory)
    await service.record_credit_snapshot(
        idempotency_key="wallet:small-confirmed",
        provider="scrapecreators",
        operation="get_reels",
        source="API_RESPONSE",
        credits_remaining=4,
        credits_charged=1,
    )

    availability = await service.available_for_scan(
        provider="scrapecreators",
        requested_units=999_999,
        daily_remaining=7,
    )

    assert availability.requested_units == 999_999
    assert availability.effective_units == 4
    assert availability.provider_balance == 4
    assert availability.provider_balance_source == "API_RESPONSE"
