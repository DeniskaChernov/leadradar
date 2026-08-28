from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.db.models import (
    AudienceMembership,
    AudienceSegment,
    Comment,
    ContactIntelligence,
    ContactInterestProfile,
    Deal,
    DealStatus,
    Evidence,
    InterestEvidence,
    Lead,
    OutcomeDNA,
)
from app.schemas.leads import CommercialSignalQuality, Intent, LeadAnalysis
from app.services.audience_service import AudienceEngine
from app.services.contact_service import ContactService
from app.services.lead_service import LeadService
from tests.test_contact_service import make_comment, make_post
from tests.test_lead_service import StaticAnalyzer


class ReactionAnalyzer:
    async def analyze(self, context):
        return LeadAnalysis(
            is_lead=False,
            lead_score=3,
            intent=Intent.REACTION,
            product_category=None,
            language="ru",
            reason="Некоммерческая реакция",
            intelligence_version="3.0",
            is_commercial=False,
            commercial_quality=CommercialSignalQuality.NON_COMMERCIAL,
        )


class AvailabilityAnalyzer:
    async def analyze(self, context):
        return LeadAnalysis(
            is_lead=True,
            lead_score=78,
            intent=Intent.AVAILABILITY,
            product_category="CHAIRS",
            language="ru",
            reason="Запрос наличия стульев",
        )


async def test_interest_evidence_and_membership_explanation_are_idempotent(
    session_factory,
):
    engine = AudienceEngine(session_factory, hot_threshold=70)
    signal = await ContactService(session_factory).persist_signal(make_post(), make_comment())
    await LeadService(
        session_factory,
        StaticAnalyzer(),
        hot_threshold=70,
        audience_engine=engine,
    ).process_signal(signal)

    await engine.recalculate_contact(signal.contact_id)
    await engine.recalculate_contact(signal.contact_id)

    async with session_factory() as session:
        assert await session.scalar(select(func.count(InterestEvidence.id))) == 2
        assert await session.scalar(select(func.count(ContactInterestProfile.id))) == 2
        price_segment = await session.scalar(
            select(AudienceSegment).where(AudienceSegment.slug == "asked-price")
        )
        membership = await session.scalar(
            select(AudienceMembership).where(
                AudienceMembership.segment_id == price_segment.id,
                AudienceMembership.contact_id == signal.contact_id,
            )
        )
        real_evidence_ids = set(await session.scalars(select(Evidence.id)))

    assert membership is not None and membership.active is True
    assert membership.engine_version == "3.0"
    assert {reason["criterion"] for reason in membership.reasons_json} >= {
        "VERTICAL",
        "INTENT",
    }
    assert set(membership.evidence_ids_json) <= real_evidence_ids
    assert membership.evidence_ids_json


async def test_reaction_does_not_create_interest_or_multi_competitor_activity(
    session_factory,
):
    engine = AudienceEngine(session_factory, hot_threshold=70)
    contact_service = ContactService(session_factory)
    first = await contact_service.persist_signal(make_post(), make_comment("commercial-v3"))
    await LeadService(
        session_factory,
        StaticAnalyzer(),
        hot_threshold=70,
        audience_engine=engine,
    ).process_signal(first)

    reaction_post = make_post().model_copy(
        update={
            "platform_post_id": "reaction-post",
            "competitor": "reaction-source.uz",
            "url": "https://www.instagram.com/reel/reaction-post/",
        }
    )
    reaction_comment = make_comment("reaction-v3").model_copy(
        update={"text": "Красиво ❤️", "platform_comment_id": "reaction-v3"}
    )
    reaction = await contact_service.persist_signal(reaction_post, reaction_comment)
    assert reaction.contact_id == first.contact_id
    await LeadService(
        session_factory,
        ReactionAnalyzer(),
        hot_threshold=70,
        audience_engine=engine,
    ).process_signal(reaction)
    await engine.recalculate_contact(first.contact_id)

    async with session_factory() as session:
        intelligence = await session.scalar(
            select(ContactIntelligence).where(
                ContactIntelligence.contact_id == first.contact_id
            )
        )
        multi = await session.scalar(
            select(AudienceMembership)
            .join(AudienceSegment, AudienceSegment.id == AudienceMembership.segment_id)
            .where(
                AudienceMembership.contact_id == first.contact_id,
                AudienceSegment.slug == "multi-competitor-2",
            )
        )
        observations = list(
            await session.scalars(
                select(InterestEvidence).where(
                    InterestEvidence.contact_id == first.contact_id
                )
            )
        )

    assert intelligence is not None and intelligence.source_count == 1
    assert multi is not None and multi.active is False
    assert {item.topic for item in observations} == {"DINING_SET", "PRICE"}


async def test_decayed_interest_expires_membership_without_deleting_history(
    session_factory,
):
    engine = AudienceEngine(session_factory, hot_threshold=70)
    signal = await ContactService(session_factory).persist_signal(make_post(), make_comment())
    await LeadService(
        session_factory,
        StaticAnalyzer(),
        hot_threshold=70,
        audience_engine=engine,
    ).process_signal(signal)

    async with session_factory() as session:
        comment = await session.get(Comment, signal.comment_id)
        comment.discovered_at = datetime.now(UTC) - timedelta(days=90)
        await session.commit()

    await engine.recalculate_contact(signal.contact_id)
    async with session_factory() as session:
        price_profile = await session.scalar(
            select(ContactInterestProfile).where(
                ContactInterestProfile.contact_id == signal.contact_id,
                ContactInterestProfile.dimension == "INTENT",
                ContactInterestProfile.topic == "PRICE",
            )
        )
        price_membership = await session.scalar(
            select(AudienceMembership)
            .join(AudienceSegment, AudienceSegment.id == AudienceMembership.segment_id)
            .where(
                AudienceMembership.contact_id == signal.contact_id,
                AudienceSegment.slug == "asked-price",
            )
        )
        historical_count = await session.scalar(select(func.count(InterestEvidence.id)))

    assert price_profile is not None and price_profile.current_score == 0
    assert price_membership is not None and price_membership.active is False
    assert historical_count == 2


async def test_outcome_dna_uses_only_pre_won_evidence(session_factory):
    engine = AudienceEngine(session_factory, hot_threshold=70)
    contact_service = ContactService(session_factory)
    first = await contact_service.persist_signal(make_post(), make_comment("pre-won"))
    await LeadService(
        session_factory,
        StaticAnalyzer(),
        hot_threshold=70,
        audience_engine=engine,
    ).process_signal(first)

    won_at = datetime.now(UTC)
    async with session_factory() as session:
        first_lead = await session.scalar(
            select(Lead).where(Lead.contact_id == first.contact_id)
        )
        session.add(
            Deal(
                contact_id=first.contact_id,
                lead_id=first_lead.id,
                status=DealStatus.WON,
                won_at=won_at,
            )
        )
        await session.commit()

    later_post = make_post().model_copy(
        update={
            "platform_post_id": "post-won-post",
            "competitor": "later-source.uz",
            "url": "https://www.instagram.com/reel/post-won-post/",
        }
    )
    later = await contact_service.persist_signal(later_post, make_comment("post-won"))
    await LeadService(
        session_factory,
        AvailabilityAnalyzer(),
        hot_threshold=70,
        audience_engine=engine,
    ).process_signal(later)
    async with session_factory() as session:
        later_comment = await session.get(Comment, later.comment_id)
        later_comment.discovered_at = won_at + timedelta(days=1)
        await session.commit()

    await engine.recalculate_contact(first.contact_id)
    async with session_factory() as session:
        dna = await session.scalar(
            select(OutcomeDNA).where(OutcomeDNA.contact_id == first.contact_id)
        )

    assert dna is not None
    assert dna.product_topics_json == ["DINING_SET"]
    assert dna.intents_json == ["PRICE"]
    assert dna.commercial_signal_count == 1
    assert dna.source_count == 1
    assert "WON" not in dna.product_topics_json + dna.intents_json
