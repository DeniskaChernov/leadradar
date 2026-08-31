from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select

from app.db.models import (
    AudienceMembership,
    AudienceSegment,
    Contact,
    ContactIntelligence,
    ExportEligibility,
    Vertical,
)
from app.services.audience_quality_service import AudienceQualityService
from app.services.audience_service import (
    RATTAN_ROLE_CRITERIA_MAP,
    AudienceEngine,
    calculate_membership_confidence,
)


@dataclass
class _Observation:
    evidence_id: int
    confidence: int
    competitor_id: int | None = None


def test_membership_confidence_caps_single_weak_evidence():
    observations = [_Observation(evidence_id=1, confidence=52, competitor_id=10)]
    score = calculate_membership_confidence(
        observations,  # type: ignore[arg-type]
        [1],
        recency_days=5,
    )
    assert score <= 52


def test_membership_confidence_rewards_source_diversity():
    single = calculate_membership_confidence(
        [
            _Observation(evidence_id=1, confidence=80, competitor_id=1),
            _Observation(evidence_id=2, confidence=78, competitor_id=1),
        ],  # type: ignore[arg-type]
        [1, 2],
        recency_days=3,
    )
    diverse = calculate_membership_confidence(
        [
            _Observation(evidence_id=1, confidence=80, competitor_id=1),
            _Observation(evidence_id=2, confidence=78, competitor_id=2),
        ],  # type: ignore[arg-type]
        [1, 2],
        recency_days=3,
    )
    assert diverse > single


def test_rattan_role_criteria_map_covers_registry_roles():
    assert RATTAN_ROLE_CRITERIA_MAP["MANUFACTURER"] == frozenset({"MANUFACTURER"})
    assert "IMPORTER" in RATTAN_ROLE_CRITERIA_MAP["IMPORT_DISTRIBUTION"]


def test_evaluate_rattan_role_requires_matching_taxonomy_role():
    now = datetime.now(UTC)
    base_facts = {
        "hot": False,
        "commercial_signals": 2,
        "current_intent_score": 70,
        "recency_days": 5,
        "products": set(),
        "intents": set(),
        "sources": 2,
        "customer_type": "B2B",
        "quantity": 0,
        "value": 70,
        "reactivated": False,
        "buyer_role": "B2B_HORECA",
        "profiles": {},
        "evidence_ids": [11, 12],
        "source_observations": [],
        "evaluated_at": now,
        "vertical": "ARTIFICIAL_RATTAN",
        "rattan_layers": {"RAW_MATERIAL"},
        "rattan_roles": {"MANUFACTURER"},
    }

    active, reasons, evidence_ids, _expires = AudienceEngine._evaluate(
        {"rattan_role": "MANUFACTURER"},
        base_facts,
        now,
    )
    assert active is True
    assert evidence_ids == [11, 12]
    assert any(reason["criterion"] == "RATTAN_ROLE" for reason in reasons)

    inactive, _, _, _ = AudienceEngine._evaluate(
        {"rattan_role": "READY_FURNITURE_SELLER"},
        base_facts,
        now,
    )
    assert inactive is False


async def test_audience_quality_service_reports_low_data_and_overlap(session_factory):
    engine = AudienceEngine(session_factory, hot_threshold=70)
    await engine.sync_segments()

    async with session_factory() as session:
        segment_a = await session.scalar(
            select(AudienceSegment).where(AudienceSegment.slug == "furniture-commercial-intent")
        )
        segment_b = await session.scalar(
            select(AudienceSegment).where(AudienceSegment.slug == "furniture-high-intent")
        )
        assert segment_a is not None and segment_b is not None

        contact = Contact(
            username="quality_overlap",
            normalized_username="quality_overlap",
            profile_url="https://instagram.com/quality_overlap",
            display_name="Quality Overlap",
        )
        session.add(contact)
        await session.flush()

        intelligence = ContactIntelligence(
            contact_id=contact.id,
            vertical=Vertical.FURNITURE,
            intent_strength=75,
            activity_score=70,
            value_score=72,
            evidence_count=2,
            source_count=2,
            primary_buyer_role="B2C_CONSUMER",
            export_eligibility=ExportEligibility.NOT_EXPORTABLE,
            first_seen_at=datetime.now(UTC),
            last_seen_at=datetime.now(UTC),
        )
        session.add(intelligence)
        session.add_all(
            [
                AudienceMembership(
                    segment_id=segment_a.id,
                    contact_id=contact.id,
                    active=True,
                    confidence=72,
                ),
                AudienceMembership(
                    segment_id=segment_b.id,
                    contact_id=contact.id,
                    active=True,
                    confidence=68,
                ),
            ]
        )
        await session.commit()

    page = await AudienceQualityService(session_factory).snapshot("FURNITURE")
    health_by_slug = {row.segment_slug: row for row in page.health_rows}
    assert health_by_slug["furniture-commercial-intent"].status == "LOW_DATA"
    assert page.overlap_rows
    assert page.overlap_rows[0].intersection == 1
    assert page.overlap_rows[0].jaccard > 0
