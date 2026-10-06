import json
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select

from app.db.models import Product, ProductChange, Vertical
from app.services.product_catalog_service import ProductCatalogService, normalize_product_category
from app.services.public_catalog_import_service import import_btt_snapshot
from tests.test_web_security import _build_test_app, _dev_settings


@pytest.fixture
def btt_snapshot():
    path = Path(__file__).parents[1] / "app/data/btt_public_catalog_2026-10-06.json"
    return json.loads(path.read_text(encoding="utf-8"))


async def test_public_catalog_preview_and_import_are_idempotent(session_factory, btt_snapshot):
    catalog = ProductCatalogService(session_factory)
    preview = await import_btt_snapshot(catalog, btt_snapshot, manager_id=1001, apply=False)
    assert preview["created"] == 27
    assert await catalog.products() == []
    result = await import_btt_snapshot(catalog, btt_snapshot, manager_id=1001, apply=True)
    assert result["created"] == 27
    again = await import_btt_snapshot(catalog, btt_snapshot, manager_id=1001, apply=True)
    assert again["created"] == again["updated"] == 0
    assert again["unchanged"] == 27
    products = await catalog.products()
    assert sum(p.price is not None for p in products) == 19
    assert all(p.currency == "UZS" for p in products)
    assert all(p.stock is None and p.stock_confirmed_at is None and p.cogs is None for p in products)
    assert all(p.category_confirmed_at is not None and p.sku is None for p in products)
    assert all(p.source_reference.startswith("https://bententrade.") for p in products)
    assert all(p.import_source == "BTT_PUBLIC" for p in products)
    async with session_factory() as session:
        assert await session.scalar(select(func.count(ProductChange.id))) == 27
    assert len(await catalog.matching_products(vertical=Vertical.FURNITURE, category="chairs")) == 7
    assert len(await catalog.matching_products(vertical=Vertical.FURNITURE, category="tables")) == 7
    sets = await catalog.matching_products(vertical=Vertical.FURNITURE, category="DINING_SET")
    assert len(sets) == 1 and sets[0].price == Decimal("1352000")
    assert sets[0].source_reference.startswith(btt_snapshot["source_url"] + "#")
    assert len(await catalog.matching_products(vertical=Vertical.ARTIFICIAL_RATTAN, category="RAW_RATTAN")) == 6


async def test_public_catalog_never_imports_zero_as_free_price(session_factory, btt_snapshot):
    btt_snapshot["products"] = [dict(btt_snapshot["products"][0], price_uzs=0, stock=1)]
    catalog = ProductCatalogService(session_factory)
    await import_btt_snapshot(catalog, btt_snapshot, manager_id=1001, apply=True)
    product = (await catalog.products())[0]
    assert product.price is None and product.price_confirmed_at is None
    assert product.stock is None and product.stock_confirmed_at is None


async def test_public_catalog_preserves_manager_confirmations(session_factory, btt_snapshot):
    catalog = ProductCatalogService(session_factory)
    await import_btt_snapshot(catalog, btt_snapshot, manager_id=1001, apply=True)
    async with session_factory() as session:
        product = await session.scalar(select(Product).where(Product.canonical_key == "btt-stul-roero"))
    await catalog.update_verified_fields(product.id, manager_id=1001, price="190000", stock=12)
    result = await import_btt_snapshot(catalog, btt_snapshot, manager_id=1001, apply=True)
    row = next(item for item in result["changes"] if item["canonical_key"] == "btt-stul-roero")
    assert row["protected_fields"] == ["price", "stock"]
    async with session_factory() as session:
        saved = await session.get(Product, product.id)
        assert saved.price == Decimal("190000") and saved.stock == 12


@pytest.mark.parametrize("bad_price", ["NaN", "Infinity", "-1", "not-a-price"])
async def test_public_catalog_rejects_bad_snapshot_atomically(session_factory, btt_snapshot, bad_price):
    btt_snapshot["products"][-1]["price_uzs"] = bad_price
    catalog = ProductCatalogService(session_factory)
    with pytest.raises(ValueError, match="цена"):
        await import_btt_snapshot(catalog, btt_snapshot, manager_id=1001, apply=True)
    assert await catalog.products() == []


async def test_catalog_renders_actual_currency(session_factory, btt_snapshot):
    await import_btt_snapshot(ProductCatalogService(session_factory), btt_snapshot, manager_id=1001, apply=True)
    app = _build_test_app(_dev_settings(web_manager_id=1001), session_factory)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://testserver") as client:
        response = await client.get("/catalog?vertical=FURNITURE")
    assert response.status_code == 200
    assert "188000.00 UZS" in response.text
    assert "$188000" not in response.text


def test_category_normalization_does_not_guess_ambiguous_furniture():
    assert normalize_product_category(" chairs ") == "CHAIR"
    assert normalize_product_category("tables") == "TABLE"
    assert normalize_product_category("wicker furniture") != "CHAIR"
