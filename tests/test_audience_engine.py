from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.db.models import (
    AudienceMembership,
    AudienceSegment,
    Comment,
    Contact,
    ContactIntelligence,
    ExportEligibility,
    Vertical,
)
from app.services.audience_service import SEGMENTS, AudienceEngine
from app.services.contact_service import ContactService
from app.services.lead_service import LeadService
from tests.test_contact_service import make_comment, make_post
from tests.test_lead_service import StaticAnalyzer


async def _active_slugs(session_factory, contact_id: int) -> set[str]:
    async with session_factory() as session:
        return set(
            await session.scalars(
                select(AudienceSegment.slug)
                .join(
                    AudienceMembership,
                    AudienceMembership.segment_id == AudienceSegment.id,
                )
                .where(
                    AudienceMembership.contact_id == contact_id,
                    AudienceMembership.active.is_(True),
                )
            )
        )


async def test_audience_engine_builds_idempotent_commercial_segments(session_factory):
    engine = AudienceEngine(session_factory, hot_threshold=70)
    signal = await ContactService(session_factory).persist_signal(make_post(), make_comment())
    service = LeadService(
        session_factory,
        StaticAnalyzer(),
        hot_threshold=70,
        audience_engine=engine,
    )
    await service.process_signal(signal)
    await engine.recalculate_contact(signal.contact_id)

    active = await _active_slugs(session_factory, signal.contact_id)
    assert {"hot-24h", "hot-7d", "hot-30d", "dining-sets", "asked-price"} <= active
    async with session_factory() as session:
        intelligence = await session.scalar(select(ContactIntelligence))
        assert intelligence is not None
        assert intelligence.signal_count == 1
        assert intelligence.commercial_signal_count == 1
        assert intelligence.export_eligibility == ExportEligibility.NOT_EXPORTABLE
        assert await session.scalar(select(func.count(AudienceSegment.id))) == len(SEGMENTS)
        assert await session.scalar(select(func.count(AudienceMembership.id))) == len(SEGMENTS)


async def test_new_competitor_recalculates_overlap_without_duplicate_person(session_factory):
    engine = AudienceEngine(session_factory, hot_threshold=70)
    service = LeadService(
        session_factory,
        StaticAnalyzer(),
        hot_threshold=70,
        audience_engine=engine,
    )
    contact_service = ContactService(session_factory)
    first = await contact_service.persist_signal(make_post(), make_comment("audience-first"))
    await service.process_signal(first)
    second_post = make_post().model_copy(
        update={
            "platform_post_id": "chinar-post",
            "competitor": "chinar.uz",
            "url": "https://www.instagram.com/reel/chinar-post/",
        }
    )
    second = await contact_service.persist_signal(
        second_post, make_comment("audience-second")
    )
    await service.process_signal(second)

    assert second.contact_id == first.contact_id
    active = await _active_slugs(session_factory, first.contact_id)
    assert "comparison-shoppers" in active
    async with session_factory() as session:
        intelligence = await session.scalar(
            select(ContactIntelligence).where(
                ContactIntelligence.contact_id == first.contact_id
            )
        )
        assert intelligence is not None
        assert intelligence.source_count == 2
        assert await session.scalar(select(func.count(Contact.id))) == 1


async def test_sync_segments_retires_duplicate_legacy_segment(session_factory):
    async with session_factory() as session:
        session.add(
            AudienceSegment(
                slug="multi-competitor-2",
                vertical=Vertical.FURNITURE,
                name="Legacy duplicate",
                description="Retired in favor of comparison-shoppers",
                criteria_json={"sources": 2},
                active=True,
            )
        )
        await session.commit()

    changed = await AudienceEngine(session_factory, hot_threshold=70).sync_segments()

    async with session_factory() as session:
        legacy = await session.scalar(
            select(AudienceSegment).where(
                AudienceSegment.slug == "multi-competitor-2"
            )
        )
    assert changed >= 1
    assert legacy is not None and legacy.active is False


async def test_username_alone_is_never_export_eligible_and_recency_expires(session_factory):
    engine = AudienceEngine(session_factory, hot_threshold=70)
    signal = await ContactService(session_factory).persist_signal(make_post(), make_comment())
    await LeadService(
        session_factory,
        StaticAnalyzer(),
        hot_threshold=70,
        audience_engine=engine,
    ).process_signal(signal)
    async with session_factory() as session:
        contact = await session.get(Contact, signal.contact_id)
        comment = await session.get(Comment, signal.comment_id)
        assert contact is not None and comment is not None
        assert contact.phone is None
        comment.discovered_at = datetime.now(UTC) - timedelta(days=40)
        await session.commit()
    await engine.recalculate_contact(signal.contact_id)

    active = await _active_slugs(session_factory, signal.contact_id)
    assert "hot-7d" not in active
    async with session_factory() as session:
        intelligence = await session.scalar(select(ContactIntelligence))
        assert intelligence is not None
        assert intelligence.export_eligibility == ExportEligibility.NOT_EXPORTABLE

        contact = await session.get(Contact, signal.contact_id)
        assert contact is not None
        contact.phone = "+998901234567"
        contact.qualification_updated_at = datetime.now(UTC)
        await session.commit()
    await engine.recalculate_contact(signal.contact_id)
    async with session_factory() as session:
        intelligence = await session.scalar(select(ContactIntelligence))
        assert intelligence is not None
        assert intelligence.export_eligibility == ExportEligibility.FIRST_PARTY_ELIGIBLE


def test_quantity_extraction_rejects_bare_prices():
    assert AudienceEngine._extract_explicit_quantities("цена 500, доставка 20") == []
    assert AudienceEngine._extract_explicit_quantities("нужно 50 стульев и 20 dona") == [50, 20]
