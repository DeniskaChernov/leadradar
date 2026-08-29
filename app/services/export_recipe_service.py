"""
export_recipe_service.py — Phase 9 Meta Catalog Mapping & Audience Export Recipes

Provides first-party eligible export recipes, Meta Catalog taxonomy mapping,
dry-run preview, and audit logging. Strictly enforces ExportEligibility gating.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, ClassVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import (
    AudienceMembership,
    AudienceSegment,
    Contact,
    ContactEvent,
    ContactEventType,
    ContactIntelligence,
    ExportEligibility,
)


class CatalogMapper:
    """Maps Lead Radar product categories to Meta/Google product taxonomy."""

    _META_TAXONOMY: ClassVar[dict[str, str]] = {
        "DINING_SET": "Home & Garden > Furniture > Dining Room Furniture > Dining Sets",
        "RATTAN_SOFA": "Home & Garden > Furniture > Outdoor Furniture > Outdoor Sofas",
        "RATTAN_ARMCHAIR": "Home & Garden > Furniture > Outdoor Furniture > Outdoor Chairs",
        "RATTAN_GARDEN_SET": "Home & Garden > Furniture > Outdoor Furniture > Outdoor Furniture Sets",
        "RATTAN_BAR_STOOL": "Home & Garden > Furniture > Bar Furniture > Bar Stools",
        "SWING": "Home & Garden > Furniture > Outdoor Furniture > Porch Swings",
        "PERGOLA": "Home & Garden > Lawn & Garden > Outdoor Living > Canopies & Gazebos",
        "RATTAN_FURNITURE": "Home & Garden > Furniture > Outdoor Furniture",
        "CHAIRS": "Home & Garden > Furniture > Chairs",
        "TABLE": "Home & Garden > Furniture > Tables",
        "OUTDOOR_FURNITURE": "Home & Garden > Furniture > Outdoor Furniture",
        "HORECA": "Business & Industrial > Hospitality & Commercial Furniture",
    }

    @classmethod
    def get_meta_category(cls, product_category: str | None) -> str:
        if not product_category:
            return "Home & Garden > Furniture"
        return cls._META_TAXONOMY.get(product_category, "Home & Garden > Furniture")


@dataclass(frozen=True, slots=True)
class ExportRecipe:
    slug: str
    name: str
    description: str
    buyer_roles: tuple[str, ...]
    segment_slug: str | None
    product_category: str | None
    min_value_score: int


RECIPES: dict[str, ExportRecipe] = {
    "b2b_horeca_wholesale": ExportRecipe(
        slug="b2b_horeca_wholesale",
        name="B2B & HoReCa Опт",
        description="Закупки для ресторанов, отелей и оптовые заказчики",
        buyer_roles=("B2B_HORECA",),
        segment_slug="furniture-b2b",
        product_category="HORECA",
        min_value_score=50,
    ),
    "designers_contractors": ExportRecipe(
        slug="designers_contractors",
        name="Дизайнеры и комплектаторы",
        description="Спецификации под дизайн-проекты и 3D-модели",
        buyer_roles=("DESIGNER_CONTRACTOR",),
        segment_slug="furniture-designers",
        product_category=None,
        min_value_score=40,
    ),
    "high_intent_dining": ExportRecipe(
        slug="high_intent_dining",
        name="Горячие обеденные группы",
        description="Розница с выверенным запросом на обеденные комплекты",
        buyer_roles=("B2C_CONSUMER", "B2B_HORECA"),
        segment_slug="furniture-dining",
        product_category="DINING_SET",
        min_value_score=60,
    ),
    "comparison_shoppers": ExportRecipe(
        slug="comparison_shoppers",
        name="Сравнивают конкурентов",
        description="Контакты, замеченные в комментариях 2+ компаний",
        buyer_roles=(),
        segment_slug="furniture-comparison",
        product_category=None,
        min_value_score=30,
    ),
}


class ExportRecipeService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    @staticmethod
    def _hash(value: str) -> str:
        """Standard SHA-256 hash for privacy-safe dry runs and Meta hashing."""
        return hashlib.sha256(value.strip().lower().encode("utf-8")).hexdigest()

    async def run_export_recipe(
        self,
        recipe_slug: str,
        *,
        dry_run: bool = True,
        manager_id: int = 1,
    ) -> dict[str, Any]:
        recipe = RECIPES.get(recipe_slug)
        if recipe is None:
            raise ValueError(f"Unknown export recipe: {recipe_slug}")

        meta_category = CatalogMapper.get_meta_category(recipe.product_category)

        async with self.session_factory() as session:
            stmt = select(Contact, ContactIntelligence).join(
                ContactIntelligence, ContactIntelligence.contact_id == Contact.id
            )

            if recipe.segment_slug:
                segment = await session.scalar(
                    select(AudienceSegment).where(AudienceSegment.slug == recipe.segment_slug)
                )
                if segment is not None:
                    stmt = stmt.join(
                        AudienceMembership,
                        (AudienceMembership.contact_id == Contact.id)
                        & (AudienceMembership.segment_id == segment.id)
                        & (AudienceMembership.active.is_(True)),
                    )

            if recipe.buyer_roles:
                stmt = stmt.where(ContactIntelligence.primary_buyer_role.in_(recipe.buyer_roles))

            if recipe.min_value_score > 0:
                stmt = stmt.where(ContactIntelligence.value_score >= recipe.min_value_score)

            rows = (await session.execute(stmt)).all()

            total_matched = len(rows)
            eligible_rows = [
                (c, intel)
                for c, intel in rows
                if intel.export_eligibility == ExportEligibility.FIRST_PARTY_ELIGIBLE
            ]
            eligible_count = len(eligible_rows)

            if dry_run:
                sample_hashes = [
                    self._hash(contact.phone or contact.username)
                    for contact, _intel in eligible_rows[:5]
                ]
                return {
                    "recipe_slug": recipe.slug,
                    "recipe_name": recipe.name,
                    "dry_run": True,
                    "total_matched": total_matched,
                    "eligible_count": eligible_count,
                    "meta_catalog_category": meta_category,
                    "sample_privacy_hashes": sample_hashes,
                    "message": f"Dry-run: Найдено {total_matched} контактов, из них {eligible_count} допустимы к экспорту (FIRST_PARTY_ELIGIBLE).",
                }

            # Confirmed export: format records and record audit events
            records = []
            now = datetime.now(UTC)
            batch_id = f"EXP-{recipe.slug}-{int(now.timestamp())}"

            for contact, intel in eligible_rows:
                phone_hash = self._hash(contact.phone) if contact.phone else None
                user_hash = self._hash(contact.username)
                records.append(
                    {
                        "contact_id": contact.id,
                        "phone_hash": phone_hash,
                        "username_hash": user_hash,
                        "buyer_role": intel.primary_buyer_role,
                        "meta_catalog_category": meta_category,
                        "exported_at": now.isoformat(),
                    }
                )
                # Update status
                intel.export_eligibility = ExportEligibility.EXPORTED

                # Audit event
                event = ContactEvent(
                    contact_id=contact.id,
                    event_type=ContactEventType.QUALIFICATION_UPDATED,
                    payload_json={
                        "action": "AUDIENCE_EXPORT",
                        "recipe_slug": recipe.slug,
                        "batch_id": batch_id,
                        "exported_by": manager_id,
                    },
                    created_at=now,
                )
                session.add(event)

            await session.commit()

            return {
                "recipe_slug": recipe.slug,
                "recipe_name": recipe.name,
                "dry_run": False,
                "batch_id": batch_id,
                "exported_count": len(records),
                "meta_catalog_category": meta_category,
                "records": records,
                "message": f"Успешно экспортировано {len(records)} записей под батчем {batch_id}.",
            }
