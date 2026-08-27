import json
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select

from app.db.models import (
    BusinessAlias,
    BusinessAliasType,
    BusinessEntity,
    BusinessEntityStatus,
    Comment,
    Contact,
    ContactEvent,
    ContactEventType,
    Evidence,
    MarketCandidate,
    PublicSignal,
    SignalSubjectType,
    SignalType,
    Vertical,
)
from app.schemas.instagram import InstagramComment, InstagramPost
from app.services.contact_service import ContactService
from app.services.entity_resolution_service import AliasCandidate, EntityResolutionService
from app.services.market_intelligence_service import MarketIntelligenceService


def post() -> InstagramPost:
    return InstagramPost(
        platform_post_id="v4-post",
        competitor="aiko.uz",
        url="https://www.instagram.com/reel/v4-post/",
        caption="Dining set",
        comments_count=2,
    )


def comment(
    external_id: str,
    *,
    user_id: str = "stable-user-1",
    username: str = "public_buyer",
) -> InstagramComment:
    return InstagramComment(
        platform_comment_id=external_id,
        platform_user_id=user_id,
        username=username,
        display_name="Public Buyer",
        profile_url=f"https://www.instagram.com/{username}/",
        text="6 kishilik bormi?",
        created_at=datetime.now(UTC),
        raw_data={"id": external_id, "public": True},
    )


async def test_comment_dual_writes_universal_signal_business_and_evidence(
    session_factory,
):
    service = ContactService(session_factory)
    first = await service.persist_signal(post(), comment("v4-comment-1"))
    second = await service.persist_signal(post(), comment("v4-comment-2"))
    duplicate = await service.persist_signal(post(), comment("v4-comment-1"))

    assert first.created is True
    assert second.created is True
    assert duplicate.created is False
    async with session_factory() as session:
        signals = list(await session.scalars(select(PublicSignal).order_by(PublicSignal.id)))
        assert len(signals) == 2
        assert signals[0].vertical == Vertical.FURNITURE
        assert signals[0].subject_type == SignalSubjectType.CONTACT
        assert signals[0].signal_type == SignalType.COMMENT
        assert signals[0].external_id == "v4-comment-1"
        assert signals[0].dedupe_key == "instagram:COMMENT:v4-comment-1"
        assert signals[0].business_id is not None
        assert signals[0].source_competitor_id == signals[0].competitor_id
        assert signals[0].text == "6 kishilik bormi?"
        assert await session.scalar(select(func.count(BusinessEntity.id))) == 1
        assert await session.scalar(select(func.count(BusinessAlias.id))) == 1
        assert await session.scalar(select(func.count(Evidence.id))) == 2
        business = await session.get(BusinessEntity, signals[0].business_id)
        assert business is not None
        assert business.verticals_json == [Vertical.FURNITURE.value]


async def test_username_reassignment_never_merges_different_platform_users(
    session_factory,
):
    service = ContactService(session_factory)
    first = await service.persist_signal(
        post(), comment("identity-1", user_id="person-a", username="shared_name")
    )
    second = await service.persist_signal(
        post(), comment("identity-2", user_id="person-b", username="shared_name")
    )

    assert first.contact_id != second.contact_id
    async with session_factory() as session:
        contacts = list(await session.scalars(select(Contact).order_by(Contact.id)))
        assert len(contacts) == 2
        assert contacts[0].platform_user_id == "person-a"
        assert contacts[0].normalized_username.startswith("__previous__:")
        assert contacts[1].platform_user_id == "person-b"
        assert contacts[1].normalized_username == "shared_name"
        event = await session.scalar(
            select(ContactEvent).where(
                ContactEvent.contact_id == contacts[0].id,
                ContactEvent.event_type == ContactEventType.CONTACT_IDENTITY_CHANGED,
            )
        )
        assert event is not None
        assert event.payload_json["new_platform_user_id"] == "person-b"


async def test_same_platform_user_can_change_username_without_new_contact(
    session_factory,
):
    service = ContactService(session_factory)
    first = await service.persist_signal(
        post(), comment("rename-1", user_id="same-person", username="old_name")
    )
    second = await service.persist_signal(
        post(), comment("rename-2", user_id="same-person", username="new_name")
    )

    assert first.contact_id == second.contact_id
    async with session_factory() as session:
        assert await session.scalar(select(func.count(Contact.id))) == 1
        contact_row = await session.get(Contact, first.contact_id)
        assert contact_row is not None
        assert contact_row.normalized_username == "new_name"
        assert await session.scalar(select(func.count(Comment.id))) == 2


async def test_verified_strong_aliases_resolve_fixture_to_one_business(
    session_factory,
):
    fixture = json.loads(
        (Path("fixtures") / "replay_business_resolution.json").read_text(
            encoding="utf-8"
        )
    )
    resolver = EntityResolutionService(session_factory)
    resolved_ids = []
    for candidate in fixture["candidates"]:
        business = await resolver.resolve(
            canonical_key=candidate["canonical_key"],
            canonical_name=candidate["canonical_name"],
            verticals={Vertical.ARTIFICIAL_RATTAN},
            aliases=[
                AliasCandidate(
                    alias_type=BusinessAliasType(item["type"]),
                    value=item["value"],
                    source_url=item.get("source_url"),
                    confidence=95,
                    verified=bool(item.get("verified")),
                )
                for item in candidate["aliases"]
            ],
        )
        resolved_ids.append(business.id)

    assert len(set(resolved_ids)) == 1
    async with session_factory() as session:
        assert await session.scalar(select(func.count(BusinessEntity.id))) == 1
        assert await session.scalar(select(func.count(BusinessAlias.id))) == 4
        business = await session.get(BusinessEntity, resolved_ids[0])
        assert business is not None
        assert business.entity_status == BusinessEntityStatus.VERIFIED
        assert business.verticals_json == [Vertical.ARTIFICIAL_RATTAN.value]


async def test_weak_brand_name_never_auto_merges_businesses(session_factory):
    resolver = EntityResolutionService(session_factory)
    first = await resolver.resolve(
        canonical_key="weak:first",
        canonical_name="Same Name",
        verticals={Vertical.FURNITURE},
        aliases=[
            AliasCandidate(BusinessAliasType.BRAND_NAME, "Same Name", verified=True)
        ],
    )
    second = await resolver.resolve(
        canonical_key="weak:second",
        canonical_name="Same Name",
        verticals={Vertical.ARTIFICIAL_RATTAN},
        aliases=[
            AliasCandidate(BusinessAliasType.BRAND_NAME, "Same Name", verified=True)
        ],
    )

    assert first.id != second.id


async def test_botanist_seed_stays_unverified_without_invented_identifiers(
    session_factory,
):
    service = MarketIntelligenceService(session_factory)
    await service.sync_catalog()
    await service.sync_catalog()

    async with session_factory() as session:
        candidate = await session.scalar(
            select(MarketCandidate).where(MarketCandidate.display_name == "BOTANIST")
        )
        assert candidate is not None
        assert candidate.vertical == Vertical.ARTIFICIAL_RATTAN
        assert candidate.contact_hint == "Emil"
        assert candidate.status == "NEEDS_VERIFICATION"
        assert candidate.instagram_handle is None
        assert candidate.website_url is None
