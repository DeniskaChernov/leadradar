from __future__ import annotations

from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.data.product_catalog import CATALOG_SOURCE_REFERENCE, CONFIRMED_PRODUCTS
from app.db.models import Lead, Product, Vertical
from app.services.next_best_action_service import ActionRecommendation, NextBestActionEngine

ALLOWED_PRODUCT_CATEGORIES = {
    "UNCONFIRMED",
    "CHAIR",
    "ARMCHAIR",
    "SOFA",
    "TABLE",
    "SET",
    "RAW_RATTAN",
}


class ProductCatalogService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def sync_confirmed_catalog(self) -> dict[str, int]:
        created = 0
        async with self.session_factory() as session:
            for seed in CONFIRMED_PRODUCTS:
                product = await session.scalar(
                    select(Product).where(Product.canonical_key == seed.canonical_key)
                )
                if product is not None:
                    continue
                session.add(
                    Product(
                        canonical_key=seed.canonical_key,
                        sku=None,
                        name=seed.name,
                        vertical=seed.vertical,
                        category="UNCONFIRMED",
                        price=seed.price,
                        currency="USD",
                        cogs=None,
                        stock=None,
                        minimum_order_quantity=seed.minimum_order_quantity,
                        dimensions_json=seed.dimensions_cm,
                        colors_json=[],
                        max_load_kg=seed.max_load_kg,
                        b2b_suitability=(
                            "BULK_CONFIRMED"
                            if seed.minimum_order_quantity is not None
                            else "UNCONFIRMED"
                        ),
                        source_reference=CATALOG_SOURCE_REFERENCE,
                        active=True,
                    )
                )
                created += 1
            await session.commit()
        return {"created": created, "total_confirmed_seeds": len(CONFIRMED_PRODUCTS)}

    async def products(self, *, vertical: str | None = None) -> list[Product]:
        stmt = select(Product).order_by(Product.active.desc(), Product.name, Product.id)
        if vertical:
            try:
                stmt = stmt.where(Product.vertical == Vertical(vertical))
            except ValueError:
                pass
        async with self.session_factory() as session:
            return list(await session.scalars(stmt))

    async def matching_products(
        self, *, vertical: Vertical, category: str | None
    ) -> list[Product]:
        if not category or category == "UNCONFIRMED":
            return []
        category_aliases = {
            "CHAIRS": "CHAIR",
            "RATTAN_CHAIR": "CHAIR",
            "RATTAN_ARMCHAIR": "ARMCHAIR",
            "RATTAN_SOFA": "SOFA",
            "TABLE": "TABLE",
            "RATTAN_TABLE": "TABLE",
            "DINING_SET": "SET",
            "RATTAN_SET": "SET",
            "RAW_RATTAN": "RAW_RATTAN",
        }
        normalized = category_aliases.get(category, category)
        async with self.session_factory() as session:
            return list(
                await session.scalars(
                    select(Product)
                    .where(
                        Product.active.is_(True),
                        Product.vertical == vertical,
                        Product.category == normalized,
                    )
                    .order_by(Product.price, Product.name)
                )
            )

    async def recommend_for_lead(
        self, lead: Lead, *, commercial_competitor_count: int = 1
    ) -> ActionRecommendation:
        details = lead.analysis_details or {}
        raw_quantity = details.get("quantity")
        try:
            quantity = int(raw_quantity) if raw_quantity is not None else None
        except (TypeError, ValueError):
            quantity = None
        matches = await self.matching_products(
            vertical=lead.vertical,
            category=lead.product_category,
        )
        return NextBestActionEngine.recommend(
            buyer_role=str(details.get("buyer_role") or details.get("v2_buyer_role") or "UNKNOWN"),
            intent=lead.intent,
            product_category=lead.product_category,
            lead_score=lead.lead_score,
            competitor_count=max(1, commercial_competitor_count),
            quantity=quantity,
            evidence_ids=tuple(details.get("evidence_ids") or ()),
            catalog_products=matches,
        )

    async def update_verified_fields(
        self,
        product_id: int,
        *,
        category: str | None = None,
        stock: str | int | None = None,
        cogs: str | Decimal | None = None,
        active: bool | None = None,
    ) -> Product:
        async with self.session_factory() as session:
            product = await session.get(Product, product_id)
            if product is None:
                raise ValueError("Товар не найден")
            if category is not None:
                normalized = category.strip().upper()
                if normalized not in ALLOWED_PRODUCT_CATEGORIES:
                    raise ValueError("Неизвестная категория товара")
                product.category = normalized
            if stock is not None:
                value = str(stock).strip()
                if value:
                    try:
                        parsed_stock = int(value)
                    except ValueError as exc:
                        raise ValueError("Остаток должен быть целым числом") from exc
                    if parsed_stock < 0:
                        raise ValueError("Остаток не может быть отрицательным")
                    product.stock = parsed_stock
                else:
                    product.stock = None
            if cogs is not None:
                value = str(cogs).strip()
                if value:
                    try:
                        parsed_cogs = Decimal(value)
                    except InvalidOperation as exc:
                        raise ValueError("Себестоимость должна быть числом") from exc
                    if parsed_cogs < 0:
                        raise ValueError("Себестоимость не может быть отрицательной")
                    product.cogs = parsed_cogs
                else:
                    product.cogs = None
            if active is not None:
                product.active = active
            await session.commit()
            return product
