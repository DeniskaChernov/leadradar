"""Regression tests после системного bug-hunt pass."""

from __future__ import annotations

import pytest

from app.services.agent_session_service import AgentSessionService
from app.services.export_recipe_service import ExportRecipeService
from app.services.mcp_gateway_service import LeadRadarMCPGateway
from app.services.product_catalog_service import ProductCatalogService
from app.web.queries import WebQueryService
from tests.test_lead_workflow import create_lead


@pytest.mark.asyncio
async def test_agent_grounded_false_when_read_tool_not_connected(session_factory):
    service = AgentSessionService(
        session_factory,
        hot_threshold=70,
        gateway=LeadRadarMCPGateway(read_service=None),
    )

    result = await service.query("Покажи лиды")

    assert result.grounded is False
    assert result.tool_calls[0].result.success is False


@pytest.mark.asyncio
async def test_agent_competitor_query_requires_competitor_id(session_factory):
    service = AgentSessionService(session_factory, hot_threshold=70)

    with pytest.raises(ValueError, match="competitor_id"):
        await service.query("Покажи спрос конкурента")


@pytest.mark.asyncio
async def test_leads_invalid_status_filter_returns_empty(session_factory):
    await create_lead(session_factory)
    queries = WebQueryService(session_factory, hot_threshold=70)

    rows = await queries.leads(status="NOT_A_REAL_STATUS")

    assert rows == []


@pytest.mark.asyncio
async def test_deals_invalid_status_filter_returns_empty(session_factory):
    queries = WebQueryService(session_factory, hot_threshold=70)

    rows = await queries.deals(status="NOT_A_REAL_STATUS")

    assert rows == []


@pytest.mark.asyncio
async def test_catalog_invalid_vertical_returns_empty(session_factory):
    service = ProductCatalogService(session_factory)
    await service.sync_confirmed_catalog()

    products = await service.products(vertical="NOT_A_VERTICAL")

    assert products == []


@pytest.mark.asyncio
async def test_export_recipe_requires_synced_segment(session_factory):
    service = ExportRecipeService(session_factory)

    with pytest.raises(ValueError, match="not synced"):
        await service.run_export_recipe("high_intent_dining", dry_run=True)
