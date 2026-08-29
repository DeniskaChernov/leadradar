from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.db.models import (
    AudienceMembership,
    AudienceSegment,
    Comment,
    ContactIntelligence,
    InterestEvidence,
)
from app.services.audience_registry import (
    ACTIVE_AUDIENCE_DEFINITIONS,
    AUDIENCE_DEFINITIONS,
    PROHIBITED_DEFINITION_CRITERIA,
)
from app.services.audience_service import AudienceEngine
from app.services.contact_service import ContactService
from app.services.lead_service import LeadService
from tests.test_audience_dna import B2BLeadAnalyzer, make_b2b_comment, make_post_for
from tests.test_contact_service import make_comment, make_post
from tests.test_lead_service import StaticAnalyzer


async def test_registry_is_finite_unique_and_contains_no_micro_audience_criteria():
    slugs = [definition.slug for definition in AUDIENCE_DEFINITIONS]

    assert len(AUDIENCE_DEFINITIONS) == 28
    assert len(slugs) == len(set(slugs))
    assert all(
        not PROHIBITED_DEFINITION_CRITERIA.intersection(definition.criteria)
        for definition in AUDIENCE_DEFINITIONS
    )
    assert all(definition.status == "ACTIVE" for definition in ACTIVE_AUDIENCE_DEFINITIONS)
    assert any(definition.status == "DRAFT" for definition in AUDIENCE_DEFINITIONS)


async def test_registry_sync_is_idempotent_and_drafts_never_get_memberships(session_factory):
    engine = AudienceEngine(session_factory, hot_threshold=70)

    assert await engine.sync_segments() == len(AUDIENCE_DEFINITIONS)
    assert await engine.sync_segments() == 0

    signal = await ContactService(session_factory).persist_signal(make_post(), make_comment())
    await LeadService(
        session_factory,
        StaticAnalyzer(),
        hot_threshold=70,
        audience_engine=engine,
    ).process_signal(signal)
    await engine.recalculate_contact(signal.contact_id)

    async with session_factory() as session:
        drafts_with_membership = list(
            await session.scalars(
                select(AudienceSegment)
                .join(
                    AudienceMembership,
                    AudienceMembership.segment_id == AudienceSegment.id,
                )
                .where(AudienceSegment.status == "DRAFT")
            )
        )

    assert drafts_with_membership == []


async def test_stale_competitor_evidence_does_not_create_comparison_audience(
    session_factory,
):
    engine = AudienceEngine(session_factory, hot_threshold=70)
    service = LeadService(
        session_factory,
        StaticAnalyzer(),
        hot_threshold=70,
        audience_engine=engine,
    )
    contacts = ContactService(session_factory)
    first = await contacts.persist_signal(make_post(), make_comment("stale-source"))
    await service.process_signal(first)
    second = await contacts.persist_signal(
        make_post_for("fresh-source.uz", "fresh-post"),
        make_comment("fresh-source"),
    )
    await service.process_signal(second)

    async with session_factory() as session:
        stale_comment = await session.get(Comment, first.comment_id)
        assert stale_comment is not None
        stale_comment.discovered_at = datetime.now(UTC) - timedelta(days=400)
        await session.commit()

    await engine.recalculate_contact(first.contact_id)
    async with session_factory() as session:
        intelligence = await session.scalar(
            select(ContactIntelligence).where(ContactIntelligence.contact_id == first.contact_id)
        )
        membership = await session.scalar(
            select(AudienceMembership)
            .join(AudienceSegment, AudienceSegment.id == AudienceMembership.segment_id)
            .where(
                AudienceMembership.contact_id == first.contact_id,
                AudienceSegment.slug == "furniture-comparison",
            )
        )

    assert intelligence is not None and intelligence.source_count == 1
    assert membership is not None and membership.active is False


async def test_membership_confidence_is_evidence_based_not_value_score(session_factory):
    engine = AudienceEngine(session_factory, hot_threshold=70)
    signal = await ContactService(session_factory).persist_signal(
        make_post(), make_b2b_comment("confidence-source")
    )
    await LeadService(
        session_factory,
        B2BLeadAnalyzer(),
        hot_threshold=70,
        audience_engine=engine,
    ).process_signal(signal)
    await engine.recalculate_contact(signal.contact_id)

    async with session_factory() as session:
        intelligence = await session.scalar(
            select(ContactIntelligence).where(ContactIntelligence.contact_id == signal.contact_id)
        )
        membership = await session.scalar(
            select(AudienceMembership)
            .join(AudienceSegment, AudienceSegment.id == AudienceMembership.segment_id)
            .where(
                AudienceMembership.contact_id == signal.contact_id,
                AudienceSegment.slug == "furniture-b2b",
            )
        )
        evidence_confidences = list(
            await session.scalars(
                select(InterestEvidence.confidence).where(
                    InterestEvidence.contact_id == signal.contact_id,
                    InterestEvidence.evidence_id.in_(membership.evidence_ids_json),
                )
            )
        )

    assert intelligence is not None and membership is not None
    assert membership.active is True
    assert evidence_confidences
    assert membership.confidence == round(sum(evidence_confidences) / len(evidence_confidences))
    assert membership.confidence != intelligence.value_score
