from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.config import Settings
from app.db.models import CostEvent, ExternalBudgetReservation, PricingConfig
from app.services.lead_workflow_service import LeadWorkflowService
from app.services.monitor_controller import MonitorController
from app.services.pricing_config_service import PricingConfigService
from app.services.usage_service import ExternalUsageService
from app.web.app import build_web_app
from app.web.queries import WebQueryService


class _PricingMonitor:
    provider = None


@pytest.mark.asyncio
async def test_finalized_paid_operation_creates_one_attributed_cost_event(session_factory):
    pricing = PricingConfigService(session_factory)
    await pricing.set_price(
        provider="scrapecreators",
        operation="get_profile",
        pricing_basis="UNIT",
        unit_price=Decimal("0.0125"),
    )
    usage = ExternalUsageService(session_factory)
    reservation_id = await usage.reserve_budget(
        "instagram",
        "get_profile",
        10,
        provider="scrapecreators",
        reservation_key="cost-test:get-profile:1",
    )
    await usage.mark_call_started(reservation_id)
    await usage.finalize_reservation(
        reservation_id,
        units=1,
        success=True,
        details={"provider": "scrapecreators"},
    )
    await usage.finalize_reservation(reservation_id, units=1, success=True)

    async with session_factory() as session:
        events = (await session.scalars(select(CostEvent))).all()
        reservation = await session.get(ExternalBudgetReservation, reservation_id)
    assert len(events) == 1
    assert events[0].provider == "scrapecreators"
    assert events[0].cost_usd == Decimal("0.012500")
    assert reservation is not None
    assert reservation.actual_cost_usd == Decimal("0.012500")


@pytest.mark.asyncio
async def test_pricing_update_preserves_history_and_activates_latest(session_factory):
    service = PricingConfigService(session_factory)
    first = await service.set_price(
        provider="openai",
        operation="lead_analysis",
        model_name="gpt-test",
        pricing_basis="TOKENS",
        input_price=Decimal("0.000001"),
        output_price=Decimal("0.000002"),
        effective_from=datetime.now(UTC) - timedelta(days=1),
    )
    second = await service.set_price(
        provider="openai",
        operation="lead_analysis",
        model_name="gpt-test",
        pricing_basis="TOKENS",
        input_price=Decimal("0.000003"),
        output_price=Decimal("0.000004"),
    )
    repeated = await service.set_price(
        provider="openai",
        operation="lead_analysis",
        model_name="gpt-test",
        pricing_basis="TOKENS",
        input_price=Decimal("0.000003"),
        output_price=Decimal("0.000004"),
    )

    active = await service.active_price(
        "openai", "lead_analysis", model_name="gpt-test"
    )
    async with session_factory() as session:
        total = await session.scalar(select(func.count(PricingConfig.id)))
        historical = await session.get(PricingConfig, first.id)
    assert total == 2
    assert historical is not None and historical.active is False
    assert active is not None and active.id == second.id
    assert repeated.id == second.id


@pytest.mark.asyncio
async def test_missing_price_is_recorded_as_unknown_not_fake_zero(session_factory):
    usage = ExternalUsageService(session_factory)
    reservation_id = await usage.reserve_budget(
        "instagram",
        "unknown_operation",
        10,
        provider="unpriced-provider",
    )
    await usage.mark_call_started(reservation_id)
    await usage.finalize_reservation(reservation_id, units=1)

    async with session_factory() as session:
        event = await session.scalar(select(CostEvent))
    assert event is not None
    assert event.cost_usd is None


@pytest.mark.asyncio
async def test_openai_token_finalize_persists_usage_and_priced_cost(session_factory):
    pricing = PricingConfigService(session_factory)
    await pricing.set_price(
        provider="openai",
        operation="lead_analysis",
        model_name="gpt-test",
        pricing_basis="TOKENS",
        input_price=Decimal("0.000001"),
        output_price=Decimal("0.000002"),
    )
    usage = ExternalUsageService(session_factory)
    reservation_id = await usage.reserve_budget(
        "openai",
        "lead_analysis",
        10,
        provider="openai",
    )
    await usage.mark_call_started(reservation_id)
    await usage.finalize_reservation(
        reservation_id,
        units=1,
        success=True,
        details={"model": "gpt-test"},
        input_tokens=1000,
        output_tokens=250,
    )

    async with session_factory() as session:
        event = await session.scalar(select(CostEvent))
    assert event is not None
    assert event.input_tokens == 1000
    assert event.output_tokens == 250
    assert event.cost_usd == Decimal("0.001500")


@pytest.mark.asyncio
async def test_system_pricing_endpoint_creates_version_without_external_calls(session_factory):
    workflow = LeadWorkflowService(session_factory, hot_threshold=70)
    app = build_web_app(
        Settings(_env_file=None, web_manager_id=1001),
        WebQueryService(session_factory, hot_threshold=70),
        workflow,
        MonitorController(_PricingMonitor()),  # type: ignore[arg-type]
        ExternalUsageService(session_factory),
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/pricing",
            json={
                "provider": "scrapecreators",
                "operation": "get_reels",
                "pricing_basis": "UNIT",
                "unit_price": "0.025",
            },
        )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    active = await PricingConfigService(session_factory).active_price(
        "scrapecreators", "get_reels"
    )
    assert active is not None
    assert active.unit_price == Decimal("0.02500000")
