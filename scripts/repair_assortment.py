"""Preview the owner's assortment correction; --apply changes saved facts locally."""

import argparse
import asyncio
import json
from pathlib import Path

from app.config import get_settings
from app.data.product_catalog import CONFIRMED_PRODUCTS
from app.db.session import create_engine, create_session_factory
from app.services.ai_service import RuleBasedLeadAnalyzer
from app.services.assortment_policy import UNSUPPORTED_CATEGORIES
from app.services.audience_service import AudienceEngine
from app.services.lead_service import LeadService
from app.services.product_catalog_service import ProductCatalogService
from app.services.public_catalog_import_service import CATEGORIES


async def repair_catalog(catalog: ProductCatalogService, snapshot: dict, *,
                         manager_id: int, apply: bool = False) -> list[dict]:
    mapping = {}
    for item in snapshot["products"]:
        if item["category"] in CATEGORIES:
            category = CATEGORIES[item["category"]][1]
            if category == "TABLE" and "rotang" in item["slug"].lower():
                category = "WICKER_TABLE"
            mapping[f"btt-{item['slug']}"] = category
    changes = []
    seeds = {seed.canonical_key: seed.vertical for seed in CONFIRMED_PRODUCTS}
    for product in await catalog.products():
        vertical = seeds.get(product.canonical_key, product.vertical) if product.import_source == "SEED" else product.vertical
        category = mapping.get(product.canonical_key, product.category)
        active = False if product.category in UNSUPPORTED_CATEGORIES else product.active
        if product.category == category and product.active == active and product.vertical == vertical:
            continue
        changes.append({"id": product.id, "category": category, "active": active, "vertical": vertical.value})
        if apply:
            await catalog.update_verified_fields(
                product.id, manager_id=manager_id,
                category=category if category != product.category else None, active=active,
                vertical=vertical,
            )
    return changes


async def run(*, apply: bool = False) -> dict:
    settings = get_settings()
    engine = create_engine(settings)
    factory = create_session_factory(engine)
    snapshot = json.loads((Path(__file__).parents[1] / "app/data/btt_public_catalog_2026-10-06.json").read_text(encoding="utf-8"))
    service = LeadService(factory, RuleBasedLeadAnalyzer(), settings.hot_lead_threshold,
                          audience_engine=AudienceEngine(factory, hot_threshold=settings.hot_lead_threshold),
                          rules_version=settings.lead_analysis_version)
    try:
        catalog = await repair_catalog(ProductCatalogService(factory), snapshot,
                                       manager_id=settings.web_manager_id, apply=apply)
        leads = await service.repair_assortment(dry_run=not apply)
        return {"catalog": catalog, "leads": leads}
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run(apply=args.apply)), ensure_ascii=False))


if __name__ == "__main__":
    main()
