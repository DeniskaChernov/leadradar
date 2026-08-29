from sqlalchemy import func, select

from app.db.models import (
    MetaAudienceBlueprint,
    MetaAudienceSync,
    MetaInterest,
    MetaTargetingRecipe,
)
from app.services.audience_registry import AUDIENCE_DEFINITIONS
from app.services.audience_service import AudienceEngine
from app.services.meta_audience_service import MetaAudiencePlanningService
from app.services.targeting_recipe_service import TargetingRecipeEngine


async def test_meta_planning_sync_is_idempotent_and_honestly_not_connected(
    session_factory,
):
    await AudienceEngine(session_factory, hot_threshold=70).sync_segments()
    service = MetaAudiencePlanningService(session_factory)

    assert await service.sync_blueprints() == len(AUDIENCE_DEFINITIONS) * 4
    assert await service.sync_blueprints() == 0

    async with session_factory() as session:
        blueprints = list(await session.scalars(select(MetaAudienceBlueprint)))
        recipes = list(await session.scalars(select(MetaTargetingRecipe)))
        interest_count = await session.scalar(select(func.count(MetaInterest.id)))
        sync_count = await session.scalar(select(func.count(MetaAudienceSync.id)))

    assert len(blueprints) == len(AUDIENCE_DEFINITIONS)
    assert len(recipes) == len(AUDIENCE_DEFINITIONS) * 3
    assert all(item.eligibility_status == "NOT_CONNECTED" for item in blueprints)
    assert all(item.status == "NOT_CONNECTED" for item in recipes)
    assert all(item.interest_ids_json == [] for item in recipes)
    assert interest_count == 0
    assert sync_count == 0


async def test_readiness_contains_no_external_audience_or_interest_ids(session_factory):
    await AudienceEngine(session_factory, hot_threshold=70).sync_segments()
    service = MetaAudiencePlanningService(session_factory)
    await service.sync_blueprints()

    readiness = await service.readiness("furniture-b2b")

    assert readiness is not None
    assert readiness["blueprint"].eligibility_status == "NOT_CONNECTED"
    assert readiness["blueprint"].suggested_interests_json == []
    assert all(recipe.interest_ids_json == [] for recipe in readiness["recipes"])


def test_targeting_engine_accepts_only_explicit_validated_interest_ids():
    disconnected = TargetingRecipeEngine.generate_recipes(audience_name="B2B")
    connected = TargetingRecipeEngine.generate_recipes(
        audience_name="B2B",
        validated_interest_ids=("2384756", "2384756", "991122"),
        meta_connected=True,
    )

    assert all(recipe.status == "NOT_CONNECTED" for recipe in disconnected)
    assert all(recipe.interest_ids == () for recipe in disconnected)
    assert connected[0].interest_ids == ("2384756", "991122")
    assert connected[1].interest_ids == ("2384756", "991122")
    assert connected[2].interest_ids == ()
