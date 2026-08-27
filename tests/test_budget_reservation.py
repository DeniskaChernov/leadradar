import asyncio
from decimal import Decimal

import pytest

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
async def test_budget_reservation_concurrent_race(session_factory):
    usage_svc = ExternalUsageService(session_factory)
    limit = 3

    # 10 concurrent reservation attempts against limit=3
    async def try_reserve():
        try:
            return await usage_svc.reserve_budget("openai", "lead_analysis", limit, units=1)
        except ExternalBudgetExceeded:
            return None

    results = await asyncio.gather(*[try_reserve() for _ in range(10)])
    successful = [r for r in results if r is not None]
    assert len(successful) <= 3


def test_cost_preview_estimation():
    preview = ExternalUsageService.preview_cost("followers_scan", 1000)
    assert preview.estimated_records == 1000
    assert preview.estimated_units == 20
    assert preview.estimated_cost_usd_min > Decimal("0")
    assert preview.estimated_cost_usd_max >= preview.estimated_cost_usd_min
