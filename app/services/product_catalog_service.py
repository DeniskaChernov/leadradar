from __future__ import annotations

import csv
import io
import re
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.data.product_catalog import CATALOG_SOURCE_REFERENCE, CONFIRMED_PRODUCTS
from app.db.models import Lead, Product, ProductChange, Vertical
from app.services.next_best_action_service import (
    ActionRecommendation,
    NextBestActionEngine,
    RankedProduct,
)

ALLOWED_PRODUCT_CATEGORIES = {
    "UNCONFIRMED",
    "CHAIR",
    "ARMCHAIR",
    "SOFA",
    "TABLE",
    "SET",
    "RAW_RATTAN",
}

CATEGORY_ALIASES = {
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
CATALOG_IMPORT_COLUMNS = {
    "canonical_key",
    "name",
    "vertical",
    "category",
    "price",
    "currency",
    "stock",
    "cogs",
    "active",
}
CATALOG_IMPORT_MAX_BYTES = 5 * 1024 * 1024
CATALOG_IMPORT_MAX_ROWS = 2_000
CANONICAL_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,254}$")


def normalize_product_category(category: str | None) -> str | None:
    if not category or category == "UNCONFIRMED":
        return None
    return CATEGORY_ALIASES.get(category, category)


class ProductCatalogService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def sync_confirmed_catalog(self) -> dict[str, int]:
        created = 0
        async with self.session_factory() as session:
            now = datetime.now(UTC)
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
                        import_source="SEED",
                        price_confirmed_at=now,
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
                return []
        async with self.session_factory() as session:
            return list(await session.scalars(stmt))

    async def matching_products(
        self, *, vertical: Vertical, category: str | None
    ) -> list[Product]:
        normalized = normalize_product_category(category)
        if normalized is None:
            return []
        async with self.session_factory() as session:
            return list(
                await session.scalars(
                    select(Product)
                    .where(
                        Product.active.is_(True),
                        Product.vertical == vertical,
                        Product.category == normalized,
                        Product.category_confirmed_at.is_not(None),
                    )
                    .order_by(Product.price, Product.name)
                )
            )

    async def recommend_for_lead(
        self, lead: Lead, *, commercial_competitor_count: int = 1
    ) -> ActionRecommendation:
        ranked, quantity = await self.ranked_products_for_lead(lead)
        details = lead.analysis_details or {}
        return NextBestActionEngine.recommend(
            buyer_role=str(details.get("buyer_role") or details.get("v2_buyer_role") or "UNKNOWN"),
            intent=lead.intent,
            product_category=lead.product_category,
            lead_score=lead.lead_score,
            competitor_count=max(1, commercial_competitor_count),
            quantity=quantity,
            evidence_ids=tuple(details.get("evidence_ids") or ()),
            catalog_products=ranked,
        )

    async def ranked_products_for_lead(
        self,
        lead: Lead,
    ) -> tuple[list[RankedProduct], int | None]:
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
        return self.rank_products(matches, quantity=quantity), quantity

    @staticmethod
    def rank_products(
        products: list[Product],
        *,
        quantity: int | None,
    ) -> list[RankedProduct]:
        ranked: list[RankedProduct] = []
        for product in products:
            if (
                quantity is not None
                and product.minimum_order_quantity is not None
                and quantity < product.minimum_order_quantity
            ):
                continue
            score = 60
            reasons = ["Совпадает подтверждённая категория товара"]
            if product.stock is not None and product.stock_confirmed_at is not None:
                if product.stock <= 0:
                    continue
                score += 20
                reasons.append("Есть подтверждённый положительный остаток")
            else:
                reasons.append("Остаток не подтверждён и требует проверки")
            if quantity is not None and product.minimum_order_quantity is not None:
                score += 10
                reasons.append("Запрошенное количество соответствует MOQ")
            if product.price is not None and product.price_confirmed_at is not None:
                score += 5
                reasons.append("Цена подтверждена источником каталога")
            ranked.append(RankedProduct(product=product, score=score, reasons=tuple(reasons)))
        return sorted(
            ranked,
            key=lambda item: (
                -item.score,
                item.product.price is None,
                item.product.price or Decimal("0"),
                item.product.name,
                item.product.id,
            ),
        )

    async def update_verified_fields(
        self,
        product_id: int,
        *,
        manager_id: int,
        category: str | None = None,
        price: str | Decimal | None = None,
        currency: str | None = None,
        stock: str | int | None = None,
        cogs: str | Decimal | None = None,
        active: bool | None = None,
    ) -> Product:
        async with self.session_factory() as session:
            product = await session.get(Product, product_id)
            if product is None:
                raise ValueError("Товар не найден")
            before = self._verified_snapshot(product)
            if category is not None:
                normalized = category.strip().upper()
                if normalized not in ALLOWED_PRODUCT_CATEGORIES:
                    raise ValueError("Неизвестная категория товара")
                product.category = normalized
                product.category_confirmed_at = (
                    datetime.now(UTC) if normalized != "UNCONFIRMED" else None
                )
                product.category_confirmed_by = (
                    manager_id if normalized != "UNCONFIRMED" else None
                )
            if price is not None:
                value = str(price).strip()
                if value:
                    try:
                        parsed_price = Decimal(value)
                    except InvalidOperation as exc:
                        raise ValueError("Цена должна быть числом") from exc
                    if not parsed_price.is_finite() or parsed_price < 0:
                        raise ValueError("Цена должна быть конечным неотрицательным числом")
                    product.price = parsed_price
                    product.price_confirmed_at = datetime.now(UTC)
                    product.price_confirmed_by = manager_id
                else:
                    product.price = None
                    product.price_confirmed_at = None
                    product.price_confirmed_by = None
            if currency is not None:
                if price is None:
                    raise ValueError("Валюту можно подтверждать только вместе с ценой")
                normalized_currency = currency.strip().upper()
                if not normalized_currency or len(normalized_currency) > 8:
                    raise ValueError("Некорректная валюта")
                product.currency = normalized_currency
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
                    product.stock_confirmed_at = datetime.now(UTC)
                    product.stock_confirmed_by = manager_id
                else:
                    product.stock = None
                    product.stock_confirmed_at = None
                    product.stock_confirmed_by = None
            if cogs is not None:
                value = str(cogs).strip()
                if value:
                    try:
                        parsed_cogs = Decimal(value)
                    except InvalidOperation as exc:
                        raise ValueError("Себестоимость должна быть числом") from exc
                    if not parsed_cogs.is_finite() or parsed_cogs < 0:
                        raise ValueError(
                            "Себестоимость должна быть конечным неотрицательным числом"
                        )
                    product.cogs = parsed_cogs
                    product.cogs_confirmed_at = datetime.now(UTC)
                    product.cogs_confirmed_by = manager_id
                else:
                    product.cogs = None
                    product.cogs_confirmed_at = None
                    product.cogs_confirmed_by = None
            if active is not None:
                product.active = active
            after = self._verified_snapshot(product)
            if before == after:
                return product
            product.catalog_version += 1
            session.add(
                ProductChange(
                    product_id=product.id,
                    change_type="MANUAL_CONFIRMATION",
                    manager_telegram_id=manager_id,
                    source="MANUAL",
                    before_json=before,
                    after_json=after,
                    catalog_version=product.catalog_version,
                )
            )
            await session.commit()
            return product

    async def import_csv(
        self,
        *,
        filename: str,
        content: bytes,
        manager_id: int,
        apply: bool,
    ) -> dict[str, object]:
        rows = self._parse_import_csv(filename, content)
        counts = {"created": 0, "updated": 0, "unchanged": 0}
        changes: list[dict[str, object]] = []
        now = datetime.now(UTC)
        async with self.session_factory() as session:
            products = {
                product.canonical_key: product
                for product in await session.scalars(select(Product))
            }
            for row in rows:
                key = str(row["canonical_key"])
                product = products.get(key)
                if product is None:
                    counts["created"] += 1
                    changes.append(
                        {
                            "canonical_key": key,
                            "status": "CREATE",
                            "fields": sorted(row),
                            "protected_fields": [],
                        }
                    )
                    if not apply:
                        continue
                    product = Product(**row, import_source="CSV", catalog_version=1)
                    self._confirm_imported_facts(product, manager_id, now)
                    session.add(product)
                    await session.flush()
                    session.add(
                        ProductChange(
                            product_id=product.id,
                            change_type="CSV_CREATE",
                            manager_telegram_id=manager_id,
                            source="CSV",
                            before_json={},
                            after_json=self._import_snapshot(product),
                            catalog_version=1,
                        )
                    )
                    products[key] = product
                    continue

                before = self._import_snapshot(product)
                changed_fields: list[str] = []
                protected_fields: list[str] = []
                for field, incoming in row.items():
                    if field == "canonical_key":
                        continue
                    current = getattr(product, field)
                    if current == incoming:
                        continue
                    if (
                        field in {"category", "price", "stock", "cogs"}
                        and getattr(product, f"{field}_confirmed_at") is not None
                    ):
                        protected_fields.append(field)
                        continue
                    if field == "currency" and product.price_confirmed_at is not None:
                        protected_fields.append(field)
                        continue
                    changed_fields.append(field)
                    if apply:
                        setattr(product, field, incoming)
                status = "UPDATE" if changed_fields else "UNCHANGED"
                counts["updated" if changed_fields else "unchanged"] += 1
                changes.append(
                    {
                        "canonical_key": key,
                        "status": status,
                        "fields": sorted(changed_fields),
                        "protected_fields": sorted(protected_fields),
                    }
                )
                if not apply or not changed_fields:
                    continue
                for field in changed_fields:
                    if field not in {"category", "price", "stock", "cogs"}:
                        continue
                    value = getattr(product, field)
                    confirmed = value not in {None, "UNCONFIRMED"}
                    setattr(product, f"{field}_confirmed_at", now if confirmed else None)
                    setattr(
                        product,
                        f"{field}_confirmed_by",
                        manager_id if confirmed else None,
                    )
                product.import_source = "CSV"
                product.catalog_version += 1
                session.add(
                    ProductChange(
                        product_id=product.id,
                        change_type="CSV_UPDATE",
                        manager_telegram_id=manager_id,
                        source="CSV",
                        before_json=before,
                        after_json=self._import_snapshot(product),
                        catalog_version=product.catalog_version,
                    )
                )
            if apply:
                await session.commit()
        return {
            "applied": apply,
            "rows": len(rows),
            **counts,
            "changes": changes,
        }

    @staticmethod
    def _confirm_imported_facts(
        product: Product,
        manager_id: int,
        now: datetime,
    ) -> None:
        for field in ("category", "price", "stock", "cogs"):
            value = getattr(product, field)
            confirmed = value not in {None, "UNCONFIRMED"}
            setattr(product, f"{field}_confirmed_at", now if confirmed else None)
            setattr(product, f"{field}_confirmed_by", manager_id if confirmed else None)

    @staticmethod
    def _parse_import_csv(filename: str, content: bytes) -> list[dict[str, object]]:
        if not filename.lower().endswith(".csv"):
            raise ValueError("Импорт каталога принимает только CSV")
        if not content:
            raise ValueError("CSV-файл пуст")
        if len(content) > CATALOG_IMPORT_MAX_BYTES:
            raise ValueError("CSV-файл превышает лимит 5 МБ")
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError("CSV должен быть в кодировке UTF-8") from exc
        reader = csv.DictReader(io.StringIO(text))
        fieldnames = [str(item) for item in (reader.fieldnames or [])]
        if len(fieldnames) != len(CATALOG_IMPORT_COLUMNS) or set(fieldnames) != CATALOG_IMPORT_COLUMNS:
            raise ValueError(
                "CSV должен содержать колонки: "
                + ", ".join(sorted(CATALOG_IMPORT_COLUMNS))
            )
        rows: list[dict[str, object]] = []
        seen: set[str] = set()
        for line_number, raw in enumerate(reader, start=2):
            if None in raw:
                raise ValueError(f"Строка {line_number}: больше значений, чем колонок")
            if len(rows) >= CATALOG_IMPORT_MAX_ROWS:
                raise ValueError("CSV содержит больше 2000 строк")
            key = str(raw["canonical_key"] or "").strip().lower()
            if not CANONICAL_KEY_RE.fullmatch(key):
                raise ValueError(f"Строка {line_number}: некорректный canonical_key")
            if key in seen:
                raise ValueError(f"Строка {line_number}: canonical_key повторяется")
            seen.add(key)
            name = str(raw["name"] or "").strip()
            if not name or len(name) > 255:
                raise ValueError(f"Строка {line_number}: некорректное название")
            try:
                vertical = Vertical(str(raw["vertical"] or "").strip().upper())
            except ValueError as exc:
                raise ValueError(f"Строка {line_number}: неизвестная вертикаль") from exc
            category = str(raw["category"] or "UNCONFIRMED").strip().upper()
            if category not in ALLOWED_PRODUCT_CATEGORIES:
                raise ValueError(f"Строка {line_number}: неизвестная категория")
            currency = str(raw["currency"] or "").strip().upper()
            if not currency or len(currency) > 8:
                raise ValueError(f"Строка {line_number}: некорректная валюта")
            try:
                price = _optional_decimal(raw["price"])
                cogs = _optional_decimal(raw["cogs"])
                stock = _optional_integer(raw["stock"])
            except (InvalidOperation, ValueError) as exc:
                raise ValueError(f"Строка {line_number}: неверное числовое значение") from exc
            if (price is not None and (not price.is_finite() or price < 0)) or (
                cogs is not None and (not cogs.is_finite() or cogs < 0)
            ):
                raise ValueError(
                    f"Строка {line_number}: цена и COGS должны быть конечными "
                    "неотрицательными числами"
                )
            if stock is not None and stock < 0:
                raise ValueError(f"Строка {line_number}: остаток не может быть отрицательным")
            active_text = str(raw["active"] or "").strip().lower()
            if active_text not in {"true", "false", "1", "0"}:
                raise ValueError(f"Строка {line_number}: active должен быть true/false")
            rows.append(
                {
                    "canonical_key": key,
                    "name": name,
                    "vertical": vertical,
                    "category": category,
                    "price": price,
                    "currency": currency,
                    "stock": stock,
                    "cogs": cogs,
                    "active": active_text in {"true", "1"},
                }
            )
        if not rows:
            raise ValueError("CSV не содержит строк каталога")
        return rows

    @staticmethod
    def _import_snapshot(product: Product) -> dict[str, object]:
        return {
            "canonical_key": product.canonical_key,
            "name": product.name,
            "vertical": product.vertical.value,
            "category": product.category,
            "price": str(product.price) if product.price is not None else None,
            "currency": product.currency,
            "stock": product.stock,
            "cogs": str(product.cogs) if product.cogs is not None else None,
            "active": product.active,
        }

    @staticmethod
    def _verified_snapshot(product: Product) -> dict[str, object]:
        return {
            "category": product.category,
            "price": str(product.price) if product.price is not None else None,
            "currency": product.currency,
            "stock": product.stock,
            "cogs": str(product.cogs) if product.cogs is not None else None,
            "active": product.active,
        }


def _optional_decimal(value: object) -> Decimal | None:
    text = str(value or "").strip()
    return Decimal(text) if text else None


def _optional_integer(value: object) -> int | None:
    text = str(value or "").strip()
    return int(text) if text else None
