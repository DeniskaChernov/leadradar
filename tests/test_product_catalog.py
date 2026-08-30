from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.config import Settings
from app.data.product_catalog import CONFIRMED_PRODUCTS
from app.db.models import Product, ProductChange
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
        manager_id=101,
        category="CHAIR",
        price="34.50",
        currency="USD",
        stock="12",
        cogs="19.25",
    )

    assert updated.category == "CHAIR"
    assert updated.stock == 12
    assert updated.cogs == Decimal("19.25")
    assert updated.price == Decimal("34.50")
    assert updated.price_confirmed_by == 101
    assert updated.catalog_version == 2
    assert updated.category_confirmed_by == 101
    assert updated.stock_confirmed_by == 101
    assert updated.cogs_confirmed_by == 101

    repeated = await service.update_verified_fields(
        product.id,
        manager_id=101,
        category="CHAIR",
        price="34.50",
        currency="USD",
        stock="12",
        cogs="19.25",
    )
    assert repeated.catalog_version == 2
    async with session_factory() as session:
        changes = int(await session.scalar(select(func.count(ProductChange.id))) or 0)
    assert changes == 1


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


def test_catalog_ranking_prefers_confirmed_stock_and_respects_moq():
    cheap_unknown = Product(
        id=1,
        canonical_key="cheap-unknown",
        name="Cheap Unknown",
        category="CHAIR",
        price=Decimal("10"),
        currency="USD",
        stock=None,
        minimum_order_quantity=None,
    )
    stocked = Product(
        id=2,
        canonical_key="stocked",
        name="Stocked",
        category="CHAIR",
        price=Decimal("15"),
        currency="USD",
        stock=4,
        stock_confirmed_at=datetime.now(UTC),
        minimum_order_quantity=None,
        price_confirmed_at=datetime.now(UTC),
    )
    bulk_only = Product(
        id=3,
        canonical_key="bulk-only",
        name="Bulk Only",
        category="CHAIR",
        price=Decimal("8"),
        currency="USD",
        stock=100,
        minimum_order_quantity=20,
    )

    ranked = ProductCatalogService.rank_products(
        [cheap_unknown, stocked, bulk_only],
        quantity=2,
    )

    assert [item.product.id for item in ranked] == [2, 1]
    assert "положительный остаток" in " ".join(ranked[0].reasons)


async def test_catalog_csv_preview_apply_is_idempotent_and_protects_confirmed_price(
    session_factory,
):
    service = ProductCatalogService(session_factory)
    await service.sync_confirmed_catalog()
    product = (await service.products())[0]
    original_price = product.price
    csv_content = (
        "canonical_key,name,vertical,category,price,currency,stock,cogs,active\n"
        f"{product.canonical_key},Updated name,{product.vertical.value},CHAIR,"
        "999,USD,5,20,true\n"
    ).encode()

    preview = await service.import_csv(
        filename="catalog.csv",
        content=csv_content,
        manager_id=101,
        apply=False,
    )
    assert preview["updated"] == 1
    assert preview["changes"][0]["protected_fields"] == ["price"]
    async with session_factory() as session:
        unchanged = await session.get(Product, product.id)
    assert unchanged is not None
    assert unchanged.name == product.name

    applied = await service.import_csv(
        filename="catalog.csv",
        content=csv_content,
        manager_id=101,
        apply=True,
    )
    assert applied["updated"] == 1
    async with session_factory() as session:
        updated = await session.get(Product, product.id)
    assert updated is not None
    assert updated.name == "Updated name"
    assert updated.category == "CHAIR"
    assert updated.price == original_price
    assert updated.stock == 5
    assert updated.cogs == Decimal("20")

    repeated = await service.import_csv(
        filename="catalog.csv",
        content=csv_content,
        manager_id=101,
        apply=True,
    )
    assert repeated["updated"] == 0
    assert repeated["unchanged"] == 1
    async with session_factory() as session:
        changes = int(await session.scalar(select(func.count(ProductChange.id))) or 0)
    assert changes == 1
