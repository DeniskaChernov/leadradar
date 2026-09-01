from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import (
    AudienceSegment,
    MetaAudienceBlueprint,
    MetaAudienceSync,
    MetaExportCandidate,
    MetaTargetingRecipe,
)
from app.services.targeting_recipe_service import TargetingRecipeEngine


class MetaAudiencePlanningService:
    """Build local activation plans without calling Meta or inventing catalog IDs."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    @staticmethod
    def _mode(segment: AudienceSegment) -> str:
        return {
            "PROSPECTING": "CORE_TARGETING",
            "RETARGETING": "CUSTOM_AUDIENCE",
            "LOOKALIKE_SEED": "LOOKALIKE_SEED",
            "EXCLUSION": "EXCLUSION",
        }.get(segment.meta_use_case, "ANALYSIS_ONLY")

    async def sync_blueprints(self) -> int:
        changed = 0
        async with self.session_factory() as session:
            stale_blueprints = list(
                await session.scalars(
                    select(MetaAudienceBlueprint)
                    .join(
                        AudienceSegment,
                        AudienceSegment.id == MetaAudienceBlueprint.audience_definition_id,
                    )
                    .where(AudienceSegment.status == "RETIRED")
                )
            )
            for blueprint in stale_blueprints:
                has_external_history = bool(
                    await session.scalar(
                        select(MetaAudienceSync.id).where(
                            MetaAudienceSync.blueprint_id == blueprint.id
                        )
                    )
                    or await session.scalar(
                        select(MetaExportCandidate.id).where(
                            MetaExportCandidate.blueprint_id == blueprint.id
                        )
                    )
                )
                if not has_external_history:
                    recipe_count = len(
                        list(
                            await session.scalars(
                                select(MetaTargetingRecipe.id).where(
                                    MetaTargetingRecipe.blueprint_id == blueprint.id
                                )
                            )
                        )
                    )
                    await session.execute(
                        delete(MetaTargetingRecipe).where(
                            MetaTargetingRecipe.blueprint_id == blueprint.id
                        )
                    )
                    await session.delete(blueprint)
                    changed += recipe_count + 1
            segments = list(
                await session.scalars(
                    select(AudienceSegment).where(AudienceSegment.status.in_(["ACTIVE", "DRAFT"]))
                )
            )
            for segment in segments:
                mode = self._mode(segment)
                blueprint = await session.scalar(
                    select(MetaAudienceBlueprint).where(
                        MetaAudienceBlueprint.audience_definition_id == segment.id,
                        MetaAudienceBlueprint.mode == mode,
                    )
                )
                first_party = mode in {"CUSTOM_AUDIENCE", "LOOKALIKE_SEED", "EXCLUSION"}
                values = {
                    "name": f"Meta plan · {segment.name}",
                    "purpose": segment.description,
                    "eligibility_status": "NOT_CONNECTED",
                    "reason": "Meta adapter и проверенный interest catalog не подключены.",
                    "first_party_required": first_party,
                    "minimum_seed_size": 100 if mode == "LOOKALIKE_SEED" else 0,
                    "data_requirements_json": ["FIRST_PARTY_IDENTIFIER"] if first_party else [],
                    "suggested_geo_json": {},
                    "suggested_interests_json": [],
                    "suggested_exclusions_json": [],
                    "suggested_broadness": "BROAD",
                    "meta_catalog_version": None,
                    "last_validated_at": None,
                    "engine_version": "4.1",
                }
                if blueprint is None:
                    blueprint = MetaAudienceBlueprint(
                        audience_definition_id=segment.id, mode=mode, **values
                    )
                    session.add(blueprint)
                    await session.flush()
                    changed += 1
                else:
                    before = tuple(getattr(blueprint, key) for key in values)
                    for key, value in values.items():
                        setattr(blueprint, key, value)
                    changed += int(before != tuple(values.values()))
                for recipe in TargetingRecipeEngine.generate_recipes(
                    audience_name=segment.name, meta_connected=False
                ):
                    row = await session.scalar(
                        select(MetaTargetingRecipe).where(
                            MetaTargetingRecipe.blueprint_id == blueprint.id,
                            MetaTargetingRecipe.strategy == recipe.recipe_type,
                            MetaTargetingRecipe.version == 1,
                        )
                    )
                    recipe_values = {
                        "name": recipe.name,
                        "objective": "ANALYSIS_ONLY",
                        "geo_json": {},
                        "age_policy": recipe.age_policy,
                        "interest_ids_json": list(recipe.interest_ids),
                        "excluded_interest_ids_json": [],
                        "custom_audience_inclusions_json": [],
                        "custom_audience_exclusions_json": [],
                        "lookalike_seed": None,
                        "broad_targeting": recipe.broad_targeting,
                        "notes": recipe.reason,
                        "confidence": 0,
                        "evidence_json": [],
                        "status": recipe.status,
                    }
                    if row is None:
                        session.add(
                            MetaTargetingRecipe(
                                blueprint_id=blueprint.id,
                                strategy=recipe.recipe_type,
                                version=1,
                                **recipe_values,
                            )
                        )
                        changed += 1
                    else:
                        before = tuple(getattr(row, key) for key in recipe_values)
                        for key, value in recipe_values.items():
                            setattr(row, key, value)
                        changed += int(before != tuple(recipe_values.values()))
            await session.commit()
        return changed

    async def readiness(self, audience_slug: str) -> dict | None:
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    select(AudienceSegment, MetaAudienceBlueprint)
                    .join(
                        MetaAudienceBlueprint,
                        MetaAudienceBlueprint.audience_definition_id == AudienceSegment.id,
                    )
                    .where(AudienceSegment.slug == audience_slug)
                )
            ).first()
            if row is None:
                return None
            segment, blueprint = row
            recipes = list(
                await session.scalars(
                    select(MetaTargetingRecipe)
                    .where(MetaTargetingRecipe.blueprint_id == blueprint.id)
                    .order_by(MetaTargetingRecipe.strategy)
                )
            )
            return {"segment": segment, "blueprint": blueprint, "recipes": recipes}
