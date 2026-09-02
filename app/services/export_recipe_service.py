"""
export_recipe_service.py — Phase 9 Meta Catalog Mapping & Audience Export Recipes

Provides first-party eligible export recipes, Meta Catalog taxonomy mapping,
dry-run preview, confirmed Custom Audience export behind fail-closed Meta gate,
and audit logging. Strictly enforces ExportEligibility gating.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, ClassVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.db.models import (
    AudienceMembership,
    AudienceSegment,
    Contact,
    ContactEventType,
    ContactIntelligence,
    ExportEligibility,
)
from app.db.repositories.events import ContactEventRepository
from app.services.meta_ads_service import MetaAdsService


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
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        meta_ads: MetaAdsService | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.meta_ads = meta_ads

    @staticmethod
    def _hash(value: str) -> str:
        """Standard SHA-256 hash for privacy-safe dry runs and Meta hashing."""
        return hashlib.sha256(value.strip().lower().encode("utf-8")).hexdigest()

    @classmethod
    def _phone_hash_for_meta(cls, phone: str) -> str | None:
        digits = re.sub(r"\D+", "", phone or "")
        if len(digits) < 8:
            return None
        return hashlib.sha256(digits.encode("utf-8")).hexdigest()

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
        rows, eligible_rows = await self._load_recipe_rows(recipe)
        total_matched = len(rows)
        eligible_count = len(eligible_rows)
        ineligible_count = total_matched - eligible_count
        sample_hashes = [
            self._hash(contact.phone or contact.username or str(contact.id))
            for contact, _intel in eligible_rows[:5]
        ]

        if dry_run:
            await self._audit_preview(
                recipe=recipe,
                manager_id=manager_id,
                rows=rows,
                eligible_rows=eligible_rows,
                total_matched=total_matched,
                eligible_count=eligible_count,
                ineligible_count=ineligible_count,
                meta_category=meta_category,
            )
            return {
                "recipe_slug": recipe.slug,
                "recipe_name": recipe.name,
                "dry_run": True,
                "total_matched": total_matched,
                "eligible_count": eligible_count,
                "ineligible_count": ineligible_count,
                "meta_catalog_category": meta_category,
                "sample_privacy_hashes": sample_hashes,
                "message": (
                    f"Dry-run: найдено {total_matched}; first-party eligible: {eligible_count}; "
                    f"ineligible: {ineligible_count}. Meta dry-run only."
                ),
            }

        meta_ads = self.meta_ads or MetaAdsService(get_settings())
        if not meta_ads.connected:
            raise RuntimeError(
                "NOT_CONNECTED · подтверждённый Meta export недоступен; используйте dry-run"
            )
        phone_hashes: list[str] = []
        exportable: list[tuple[Contact, ContactIntelligence]] = []
        for contact, intel in eligible_rows:
            digest = self._phone_hash_for_meta(contact.phone or "")
            if digest is None:
                continue
            phone_hashes.append(digest)
            exportable.append((contact, intel))
        if not phone_hashes:
            raise RuntimeError(
                "Нет first-party контактов с телефоном для Custom Audience export"
            )

        result = await meta_ads.create_custom_audience(
            name=f"Lead Radar · {recipe.name}",
            phone_hashes=phone_hashes,
            description=recipe.description,
        )
        if result.get("error"):
            raise RuntimeError(
                f"{result.get('error')} · {result.get('message') or 'Meta Custom Audience failed'}"
            )

        await self._mark_exported(
            recipe=recipe,
            manager_id=manager_id,
            exportable=exportable,
            meta_result=result,
            meta_category=meta_category,
            total_matched=total_matched,
            eligible_count=eligible_count,
            ineligible_count=ineligible_count,
        )
        return {
            "recipe_slug": recipe.slug,
            "recipe_name": recipe.name,
            "dry_run": False,
            "total_matched": total_matched,
            "eligible_count": eligible_count,
            "ineligible_count": ineligible_count,
            "exported_count": len(exportable),
            "meta_catalog_category": meta_category,
            "meta_audience_id": result.get("audience_id"),
            "meta_status": result.get("status"),
            "sample_privacy_hashes": sample_hashes,
            "message": (
                f"Custom Audience PAUSED · id={result.get('audience_id')} · "
                f"uploaded={len(exportable)}"
            ),
        }

    async def _load_recipe_rows(
        self, recipe: ExportRecipe
    ) -> tuple[list[tuple[Contact, ContactIntelligence]], list[tuple[Contact, ContactIntelligence]]]:
        async with self.session_factory() as session:
            stmt = select(Contact, ContactIntelligence).join(
                ContactIntelligence, ContactIntelligence.contact_id == Contact.id
            )

            if recipe.segment_slug:
                segment = await session.scalar(
                    select(AudienceSegment).where(AudienceSegment.slug == recipe.segment_slug)
                )
                if segment is None:
                    raise ValueError(
                        f"Audience segment '{recipe.segment_slug}' is not synced; "
                        "run audience recalculation before export preview."
                    )
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

            rows = list((await session.execute(stmt)).all())
            eligible_rows = [
                (c, intel)
                for c, intel in rows
                if intel.export_eligibility == ExportEligibility.FIRST_PARTY_ELIGIBLE
            ]
            return rows, eligible_rows

    async def _audit_preview(
        self,
        *,
        recipe: ExportRecipe,
        manager_id: int,
        rows: list[tuple[Contact, ContactIntelligence]],
        eligible_rows: list[tuple[Contact, ContactIntelligence]],
        total_matched: int,
        eligible_count: int,
        ineligible_count: int,
        meta_category: str,
    ) -> None:
        audit_contact_id = None
        if eligible_rows:
            audit_contact_id = eligible_rows[0][0].id
        elif rows:
            audit_contact_id = rows[0][0].id
        if audit_contact_id is None:
            return
        async with self.session_factory() as session:
            await ContactEventRepository(session).add(
                audit_contact_id,
                ContactEventType.AUDIENCE_EXPORT_PREVIEW,
                manager_telegram_id=manager_id,
                payload={
                    "action": "AUDIENCE_EXPORT_PREVIEW",
                    "recipe_slug": recipe.slug,
                    "dry_run": True,
                    "total_matched": total_matched,
                    "eligible_count": eligible_count,
                    "ineligible_count": ineligible_count,
                    "meta_catalog_category": meta_category,
                },
            )
            await session.commit()

    async def _mark_exported(
        self,
        *,
        recipe: ExportRecipe,
        manager_id: int,
        exportable: list[tuple[Contact, ContactIntelligence]],
        meta_result: dict[str, Any],
        meta_category: str,
        total_matched: int,
        eligible_count: int,
        ineligible_count: int,
    ) -> None:
        async with self.session_factory() as session:
            events = ContactEventRepository(session)
            for contact, _intel in exportable:
                intel = await session.scalar(
                    select(ContactIntelligence).where(
                        ContactIntelligence.contact_id == contact.id
                    )
                )
                if intel is None:
                    continue
                intel.export_eligibility = ExportEligibility.EXPORTED
                await events.add(
                    contact.id,
                    ContactEventType.AUDIENCE_EXPORT,
                    manager_telegram_id=manager_id,
                    payload={
                        "action": "AUDIENCE_EXPORT",
                        "recipe_slug": recipe.slug,
                        "dry_run": False,
                        "meta_audience_id": meta_result.get("audience_id"),
                        "meta_status": meta_result.get("status"),
                        "meta_catalog_category": meta_category,
                        "total_matched": total_matched,
                        "eligible_count": eligible_count,
                        "ineligible_count": ineligible_count,
                        "exported_count": len(exportable),
                    },
                )
            await session.commit()
