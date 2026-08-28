from __future__ import annotations

from decimal import Decimal

from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.config import Settings
from app.data.product_catalog import CONFIRMED_PRODUCTS
from app.db.models import Product
from app.services.lead_workflow_service import LeadWorkflowService
from app.services.monitor_controller import MonitorController
from app.services.product_catalog_service import ProductCatalogService
from app.web.app import build_web_app
from app.web.queries import WebQueryService


class FakeMonitor:
    provider = None


async def test_confirmed_catalog_sync_is_idempotent_and_preserves_unknowns(session_factory):
    service = ProductCatalogService(session_factory)

    first = await service.sync_confirmed_catalog()
    second = await service.sync_confirmed_catalog()

    assert first["created"] == len(CONFIRMED_PRODUCTS)
    assert second["created"] == 0
    async with session_factory() as session:
        products = list(await session.scalars(select(Product).order_by(Product.id)))
    assert len(products) == len(CONFIRMED_PRODUCTS)
    assert all(product.sku is None for product in products)
    assert all(product.stock is None for product in products)
    assert all(product.cogs is None for product in products)
    assert {product.name for product in products} >= {"CORDA", "VERTEX", "TODO", "JARDIN"}


async def test_manager_can_confirm_category_stock_and_cogs(session_factory):
    service = ProductCatalogService(session_factory)
    await service.sync_confirmed_catalog()
    product = (await service.products())[0]

    updated = await service.update_verified_fields(
        product.id,
        category="CHAIR",
        stock="12",
        cogs="19.25",
    )

    assert updated.category == "CHAIR"
    assert updated.stock == 12
    assert updated.cogs == Decimal("19.25")


async def test_catalog_page_and_agent_not_connected_state(session_factory):
    service = ProductCatalogService(session_factory)
    await service.sync_confirmed_catalog()
    settings = Settings(_env_file=None, web_enabled=True, instagram_provider="replay")
    app = build_web_app(
        settings,
        WebQueryService(session_factory, hot_threshold=70),
        LeadWorkflowService(session_factory, hot_threshold=70),
        MonitorController(FakeMonitor()),  # type: ignore[arg-type]
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        catalog = await client.get("/catalog")
        agent = await client.post("/api/agent/query", json={"query": "Что предложить?"})

    assert catalog.status_code == 200
    assert "CORDA" in catalog.text
    assert "не подтверждён" in catalog.text
    assert "SKU-DINING-SET-6P" not in catalog.text
    assert agent.status_code == 503
    assert "не подключён" in agent.json()["detail"]


async def test_catalog_count_is_stable_after_repeated_sync(session_factory):
    service = ProductCatalogService(session_factory)
    await service.sync_confirmed_catalog()
    await service.sync_confirmed_catalog()
    async with session_factory() as session:
        count = int(await session.scalar(select(func.count(Product.id))) or 0)
    assert count == len(CONFIRMED_PRODUCTS)
