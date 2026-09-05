"""Phase 4 economics: /economics page, credits-per-outcome и OpenAI token ledger."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.config import Settings
from app.db.models import CostEvent, ProviderBudgetPolicy
from app.services.ai_service import OpenAILeadAnalyzer
from app.services.economics_page_service import EconomicsPageService
from app.services.lead_workflow_service import LeadWorkflowService
from app.services.monitor_controller import MonitorController
from app.services.pricing_config_service import PricingConfigService
from app.services.provider_credit_budget_service import ProviderCreditBudgetService
from app.services.usage_service import ExternalUsageService
from app.web.app import build_web_app
from app.web.queries import WebQueryService
from tests.test_unit_economics import _commercial_fixture, _EconomicsMonitor


def test_base_template_includes_economics_navigation_link():
    from pathlib import Path

    content = Path("app/web/templates/base.html").read_text(encoding="utf-8")
    assert 'href="/economics"' in content
    assert "Расходы" in content


async def _seed_scrapecreators_policy(session_factory) -> None:
    async with session_factory() as session:
        existing = await session.scalar(
            select(ProviderBudgetPolicy).where(
                ProviderBudgetPolicy.provider == "scrapecreators"
            )
        )
        if existing is not None:
            return
        session.add(
            ProviderBudgetPolicy(
                provider="scrapecreators",
                service="instagram",
                monthly_target_units=3000,
                monthly_soft_limit_units=3500,
                monthly_hard_limit_units=3800,
                default_scan_budget_units=10,
                maximum_manual_scan_budget_units=50,
                target_minimum_months=6,
                comments_target_units=2400,
                discovery_target_units=600,
                enrichment_target_units=200,
                reserve_target_units=600,
                active=True,
            )
        )
        await session.commit()


async def test_month_credits_low_when_remaining_under_20_percent(session_factory):
    await _seed_scrapecreators_policy(session_factory)
    service = ProviderCreditBudgetService(session_factory)
    async with session_factory() as session:
        session.add(
            CostEvent(
                idempotency_key="economics:month-low",
                service="instagram",
                provider="scrapecreators",
                operation="get_comment_batch",
                units=3500,
                cost_usd=Decimal("10.000000"),
            )
        )
        await session.commit()

    snapshot = await service.snapshot("scrapecreators")
    assert snapshot is not None
    assert snapshot.monthly_remaining <= int(snapshot.monthly_hard_limit * 0.2)
    assert snapshot.month_credits_low is True


async def test_provider_snapshot_reports_burn_months_and_status(session_factory):
    await _seed_scrapecreators_policy(session_factory)
    service = ProviderCreditBudgetService(session_factory)
    await service.record_credit_snapshot(
        idempotency_key="economics:wallet",
        provider="scrapecreators",
        operation="get_reels",
        source="API_RESPONSE",
        credits_remaining=21_842,
        credits_charged=1,
    )
    async with session_factory() as session:
        session.add(
            CostEvent(
                idempotency_key="economics:monthly-comment",
                service="instagram",
                provider="scrapecreators",
                operation="get_comment_batch",
                units=120,
                cost_usd=Decimal("1.500000"),
            )
        )
        await session.commit()

    snapshot = await service.snapshot("scrapecreators")

    assert snapshot is not None
    assert snapshot.credits_remaining == 21_842
    assert snapshot.used_this_month == 120
    assert snapshot.average_daily_burn_7d >= 0
    assert snapshot.projected_monthly_burn > 0
    assert snapshot.months_remaining is not None
    assert len(snapshot.daily_burn_series) == 7
    assert all(isinstance(day, str) and isinstance(units, int) for day, units in snapshot.daily_burn_series)
    assert sum(units for _day, units in snapshot.daily_burn_series) >= 120
    assert snapshot.month_credits_low is False
    assert snapshot.budget_status in {
        "HEALTHY",
        "WATCH",
        "HIGH",
        "BLOCKED",
        "LOW_BALANCE",
        "UNKNOWN",
    }
    assert snapshot.usage_by_operation["get_comment_batch"] == 120


async def test_wallet_unknown_balance_yields_none_months(session_factory):
    await _seed_scrapecreators_policy(session_factory)
    service = ProviderCreditBudgetService(session_factory)
    snapshot = await service.snapshot("scrapecreators")
    assert snapshot is not None
    assert snapshot.credits_remaining is None
    assert snapshot.months_remaining is None
    assert snapshot.budget_status == "UNKNOWN"


async def test_operation_breakdown_maps_comments_and_targets(session_factory):
    await _seed_scrapecreators_policy(session_factory)
    async with session_factory() as session:
        session.add_all(
            [
                CostEvent(
                    idempotency_key="economics:op-comments",
                    service="instagram",
                    provider="scrapecreators",
                    operation="get_comment_batch",
                    units=50,
                    cost_usd=Decimal("0.500000"),
                ),
                CostEvent(
                    idempotency_key="economics:op-discovery",
                    service="instagram",
                    provider="scrapecreators",
                    operation="get_reels",
                    units=10,
                    cost_usd=Decimal("0.100000"),
                ),
            ]
        )
        await session.commit()

    page = await EconomicsPageService(session_factory, hot_threshold=70).snapshot(30)
    rows = {row.bucket: row for row in page.operation_rows}

    assert rows["comments"].credits_month == 50
    assert rows["discovery"].credits_month == 10
    assert rows["comments"].planning_target == 2400
    assert rows["discovery"].planning_target == 600


async def test_credits_per_outcome_null_without_provider_events(session_factory):
    await _commercial_fixture(session_factory)
    page = await EconomicsPageService(session_factory, hot_threshold=70).snapshot(30)

    assert page.credits.known_credits == 0
    assert page.credits.credits_per_lead is None
    assert page.credits.hot_per_1000_credits is None


async def test_credits_per_lead_when_scrapecreators_events_exist(session_factory):
    await _commercial_fixture(session_factory)
    async with session_factory() as session:
        session.add(
            CostEvent(
                idempotency_key="economics:credits-lead",
                service="instagram",
                provider="scrapecreators",
                operation="get_comment_batch",
                units=40,
                cost_usd=Decimal("0.500000"),
            )
        )
        await session.commit()

    page = await EconomicsPageService(session_factory, hot_threshold=70).snapshot(30)

    assert page.credits.known_credits == 40
    assert page.credits.credits_per_lead == Decimal("40.00")
    assert page.credits.hot_per_1000_credits == Decimal("25.00")


async def test_openai_finalize_persists_actual_tokens_and_token_based_cost(
    session_factory,
):
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
        input_tokens=1200,
        output_tokens=300,
    )

    async with session_factory() as session:
        event = await session.scalar(select(CostEvent))
    assert event is not None
    assert event.input_tokens == 1200
    assert event.output_tokens == 300
    assert event.cost_usd == Decimal("0.001800")


async def test_openai_extract_token_usage_returns_none_without_usage():
    assert OpenAILeadAnalyzer._extract_token_usage(SimpleNamespace()) == (None, None)
    assert OpenAILeadAnalyzer._extract_token_usage(
        SimpleNamespace(usage=SimpleNamespace(input_tokens=120, output_tokens=30))
    ) == (120, 30)


async def test_economics_page_renders_sections_and_honest_unknowns(session_factory):
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
        response = await client.get("/economics?days=7")

    assert response.status_code == 200
    assert "КРЕДИТНЫЙ БЮДЖЕТ ПРОВАЙДЕРОВ" in response.text
    assert "Расходы AI" in response.text
    assert "Стоимость воронки" in response.text
    assert "Выручка и маржа" in response.text
    assert "Эффективность источников" in response.text
    assert "Экономика по вертикалям" in response.text
    assert "ROI не подменяется догадкой" in response.text
    assert "7 дней" in response.text


async def test_analytics_page_excludes_money_metrics(session_factory):
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
        response = await client.get("/analytics")

    assert response.status_code == 200
    assert "Стоимость лида" not in response.text
    assert "ROI не подменяется догадкой" not in response.text
    assert "АНАЛИТИКА" in response.text or "Спрос, воронка" in response.text
    assert "Воронка лидов" in response.text


async def test_analytics_days_filter_excludes_old_leads(session_factory):
    from datetime import UTC, datetime, timedelta

    from app.db.models import Lead
    from tests.test_lead_workflow import create_lead

    await create_lead(session_factory, comment_id="analytics-new", user_id="analytics-new")
    old_id = await create_lead(session_factory, comment_id="analytics-old", user_id="analytics-old")
    async with session_factory() as session:
        old = await session.get(Lead, old_id)
        assert old is not None
        old.created_at = datetime.now(UTC) - timedelta(days=10)
        await session.commit()

    queries = WebQueryService(session_factory, hot_threshold=70)
    day1 = await queries.analytics(days=1)
    day30 = await queries.analytics(days=30)
    total_1 = sum(day1["funnel"].values())
    total_30 = sum(day30["funnel"].values())
    assert total_1 >= 1
    assert total_30 >= total_1 + 1