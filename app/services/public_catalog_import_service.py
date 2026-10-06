"""Import a reviewed public BTT catalog snapshot without inventing stock or prices."""

import csv
import io
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit

from app.services.product_catalog_service import CATALOG_IMPORT_COLUMNS, ProductCatalogService

BTT_ORIGIN = "https://bententrade.denisblackman2.workers.dev"
CATEGORIES = {
    "wicker-chairs": ("FURNITURE", "CHAIR"),
    "plastic-chairs": ("FURNITURE", "CHAIR"),
    "tables": ("FURNITURE", "TABLE"),
    "lighting": ("FURNITURE", "LAMP"),
    "rattan-raw": ("ARTIFICIAL_RATTAN", "RAW_RATTAN"),
    "sets": ("FURNITURE", "SET"),
}


async def import_btt_snapshot(
    catalog: ProductCatalogService, snapshot: dict, *, manager_id: int, apply: bool,
) -> dict[str, object]:
    if snapshot.get("source_url") != f"{BTT_ORIGIN}/catalog":
        raise ValueError("Неизвестный источник каталога BTT")
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=sorted(CATALOG_IMPORT_COLUMNS))
    writer.writeheader()
    references = {}
    for item in snapshot.get("products", []):
        if item.get("category") not in CATEGORIES:
            raise ValueError("Неизвестная категория публичного каталога")
        vertical, category = CATEGORIES[item["category"]]
        slug = str(item.get("slug", ""))
        # The regular catalog parser validates canonical keys before any database write.
        key = f"btt-{slug}"
        try:
            price = Decimal(str(item.get("price_uzs") or "0"))
        except InvalidOperation as exc:
            raise ValueError("Некорректная цена публичного каталога") from exc
        if not price.is_finite() or price < 0:
            raise ValueError("Некорректная цена публичного каталога")
        writer.writerow({
            "canonical_key": key, "name": item.get("name", ""),
            "vertical": vertical, "category": category,
            # Zero on this storefront means an unspecified price, never a free product.
            "price": str(price) if price > 0 else "", "currency": "UZS",
            # data-stock=1 is a UI flag, not a verified quantity. No COGS is published.
            "stock": "", "cogs": "", "active": "true",
        })
        source_url = item.get("source_url") or f"{BTT_ORIGIN}/catalog/{slug}"
        parsed = urlsplit(source_url)
        if parsed.scheme != "https" or parsed.netloc != urlsplit(BTT_ORIGIN).netloc:
            raise ValueError("Источник товара должен принадлежать каталогу BTT")
        references[key] = f"{source_url} (срез {snapshot.get('observed_on', 'не указан')})"
    return await catalog.import_csv(
        filename="btt-public-catalog.csv", content=buffer.getvalue().encode("utf-8"),
        manager_id=manager_id, apply=apply, source_references=references, import_source="BTT_PUBLIC",
    )
