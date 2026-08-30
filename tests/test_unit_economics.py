"""Offline tests for DB-backed unit economics."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.config import Settings
from app.db.models import CostEvent, Deal, DealSaleSnapshot, DealStatus, Lead
from app.services.contact_service import ContactService
from app.services.fx_policy_service import FxPolicyService
from app.services.lead_service import LeadService
from app.services.lead_workflow_service import LeadWorkflowService
from app.services.monitor_controller import MonitorController
from app.services.unit_economics_service import UnitEconomicsEngine
from app.services.usage_service import ExternalUsageService
from app.web.app import build_web_app
from app.web.queries import WebQueryService
from tests.test_contact_service import make_comment, make_post
from tests.test_lead_service import StaticAnalyzer


class _EconomicsMonitor:
    provider = None


async def _commercial_fixture(session_factory) -> tuple[int, int]:
    signal = await ContactService(session_factory).persist_signal(
        make_post(), make_comment("economics-signal")
    )
    await LeadService(session_factory, StaticAnalyzer(), hot_threshold=70).process_signal(
        signal
    )
    async with session_factory() as session:
        lead = await session.scalar(select(Lead))
        assert lead is not None
        lead.analysis_details = {
            **(lead.analysis_details or {}),
            "buyer_role": "B2B_HORECA",
        }
        deal = Deal(
            contact_id=lead.contact_id,
            lead_id=lead.id,
            status=DealStatus.WON,
            final_amount=Decimal("12500000"),
            won_at=datetime.now(UTC),
        )
        session.add(deal)
        await session.flush()
        session.add(
            DealSaleSnapshot(
                deal_id=deal.id,
                product_name="Snapshot product",
                quantity=1,
                sale_amount=Decimal("12500000"),
                sale_currency="UZS",
                evidence_ids_json=[],
                manager_telegram_id=1,
            )
        )
        await session.commit()
        return lead.id, lead.competitor_id


async def test_snapshot_uses_persisted_costs_and_outcomes(session_factory):
    lead_id, competitor_id = await _commercial_fixture(session_factory)
    async with session_factory() as session:
        session.add(
            CostEvent(
                idempotency_key="economics:priced",
                service="openai",
                provider="openai",
                operation="lead_analysis",
                lead_id=lead_id,
                units=1,
                cost_usd=Decimal("10"),
            )
        )
        await session.commit()

    report = await UnitEconomicsEngine(session_factory, hot_threshold=70).snapshot(30)

    assert report.known_spend_usd == Decimal("10.000000")
    assert report.cost_coverage_percent == Decimal("100.00")
    assert report.signals_count == 1
    assert report.commercial_leads_count == 1
    assert report.leads_count == 1
    assert report.hot_count == 1
    assert report.b2b_count == 1
    assert report.won_count == 1
    assert report.revenue_uzs == Decimal("12500000.000000")
    assert report.cost_per_signal_usd == Decimal("10.000000")
    assert report.cost_per_commercial_signal_usd == Decimal("10.000000")
    assert report.cost_per_lead_usd == Decimal("10.000000")
    assert report.cost_per_hot_usd == Decimal("10.000000")
    assert report.cost_per_b2b_usd == Decimal("10.000000")
    assert report.cost_per_won_usd == Decimal("10.000000")
    assert report.roi_ratio is None
    assert "COGS" in report.roi_status
    source = next(item for item in report.sources if item.competitor_id == competitor_id)
    assert source.known_spend_usd == Decimal("10.000000")
    assert source.cost_events == 1
    assert source.cost_per_lead_usd == Decimal("10.000000")


async def test_unknown_price_blocks_cost_per_metrics_instead_of_fake_zero(
    session_factory,
):
    lead_id, _competitor_id = await _commercial_fixture(session_factory)
    async with session_factory() as session:
        session.add_all(
            [
                CostEvent(
                    idempotency_key="economics:known",
                    service="openai",
                    provider="openai",
                    operation="lead_analysis",
                    lead_id=lead_id,
                    units=1,
                    cost_usd=Decimal("2"),
                ),
                CostEvent(
                    idempotency_key="economics:unknown",
                    service="instagram",
                    provider="unpriced-provider",
                    operation="get_comments",
                    units=1,
                    cost_usd=None,
                ),
            ]
        )
        await session.commit()

    report = await UnitEconomicsEngine(session_factory, hot_threshold=70).snapshot(30)

    assert report.known_spend_usd == Decimal("2.000000")
    assert report.unpriced_events == 1
    assert report.cost_coverage_percent == Decimal("50.00")
    assert report.cost_per_signal_usd is None
    assert report.cost_per_lead_usd is None
    assert report.cost_per_won_usd is None
    assert "не все расходы" in report.roi_status


async def test_source_account_attribution_works_without_direct_foreign_key(
    session_factory,
):
    _lead_id, competitor_id = await _commercial_fixture(session_factory)
    async with session_factory() as session:
        session.add(
            CostEvent(
                idempotency_key="economics:handle-attribution",
                service="instagram",
                provider="scrapecreators",
                operation="get_reels",
                units=1,
                cost_usd=Decimal("0.25"),
                details_json={"source_account": "@aiko.uz"},
            )
        )
        await session.commit()

    report = await UnitEconomicsEngine(session_factory, hot_threshold=70).snapshot(30)

    assert report.attribution_missing_events == 0
    source = next(item for item in report.sources if item.competitor_id == competitor_id)
    assert source.known_spend_usd == Decimal("0.250000")


async def test_empty_ledger_returns_unknown_costs_not_zero_cost_claims(session_factory):
    report = await UnitEconomicsEngine(session_factory, hot_threshold=70).snapshot(7)

    assert report.cost_events == 0
    assert report.known_spend_usd == Decimal("0.000000")
    assert report.cost_coverage_percent == Decimal("0.00")
    assert report.cost_per_signal_usd is None
    assert report.cost_per_lead_usd is None
    assert report.roi_ratio is None
    assert "нет записанных cost events" in report.roi_status


async def test_complete_snapshot_cogs_and_historical_fx_enable_margin_and_roi(
    session_factory,
):
    lead_id, _competitor_id = await _commercial_fixture(session_factory)
    async with session_factory() as session:
        snapshot = await session.scalar(select(DealSaleSnapshot))
        assert snapshot is not None
        snapshot.cogs = Decimal("100")
        snapshot.catalog_currency = "USD"
        session.add(
            CostEvent(
                idempotency_key="economics:complete",
                service="openai",
                provider="openai",
                operation="lead_analysis",
                lead_id=lead_id,
                units=1,
                cost_usd=Decimal("10"),
            )
        )
        await session.commit()
    await FxPolicyService(session_factory).set_rate(
        base_currency="USD",
        quote_currency="UZS",
        rate=Decimal("12500"),
        manager_id=101,
        effective_from=datetime.now(UTC) - timedelta(days=1),
    )

    report = await UnitEconomicsEngine(session_factory, hot_threshold=70).snapshot(30)

    assert report.revenue_uzs == Decimal("12500000.000000")
    assert report.gross_profit_uzs == Decimal("11250000.000000")
    assert report.gross_margin_ratio == Decimal("0.9000")
    assert report.roi_ratio == Decimal("89.0000")
    assert "рассчитан" in report.roi_status


async def test_won_without_sale_snapshot_blocks_revenue_and_profit(session_factory):
    await _commercial_fixture(session_factory)
    async with session_factory() as session:
        snapshot = await session.scalar(select(DealSaleSnapshot))
        assert snapshot is not None
        await session.delete(snapshot)
        await session.commit()

    report = await UnitEconomicsEngine(session_factory, hot_threshold=70).snapshot(30)

    assert report.revenue_uzs is None
    assert report.gross_profit_uzs is None
    assert report.sale_snapshot_missing_deals == 1
    assert "sale snapshot" in report.roi_status


async def test_fx_policy_is_versioned_and_idempotent(session_factory):
    service = FxPolicyService(session_factory)
    first = await service.set_rate(
        base_currency="usd",
        quote_currency="uzs",
        rate=Decimal("12000"),
        manager_id=101,
    )
    repeated = await service.set_rate(
        base_currency="USD",
        quote_currency="UZS",
        rate=Decimal("12000"),
        manager_id=101,
    )
    changed = await service.set_rate(
        base_currency="USD",
        quote_currency="UZS",
        rate=Decimal("12500"),
        manager_id=202,
    )

    assert repeated.id == first.id
    assert changed.id != first.id
    assert await service.rate_at("USD", "UZS", datetime.now(UTC)) == Decimal("12500")
    assert len(await service.list_active()) == 1


async def test_analytics_page_renders_honest_unit_economics(session_factory):
    app = build_web_app(
        Settings(_env_file=None),
        WebQueryService(session_factory, hot_threshold=70),
        LeadWorkflowService(session_factory, hot_threshold=70),
        MonitorController(_EconomicsMonitor()),  # type: ignore[arg-type]
        ExternalUsageService(session_factory),
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/analytics?days=7")

    assert response.status_code == 200
    assert "Стоимость лида" in response.text
    assert "ROI не подменяется догадкой" in response.text
    assert "7 дней" in response.text
