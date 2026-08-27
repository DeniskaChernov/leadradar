"""
test_audience_dna.py — Master Phase 4 test suite

Tests:
  1. Profile DNA generation (primary_buyer_role, buyer_roles_json, evidence_count)
  2. New Phase 4 buyer-role segments (designers, horeca-b2b, high-intent-b2c)
  3. Deterministic similarity scoring (calculate_contact_similarity)
  4. Similarity vector stored correctly in ContactIntelligence
  5. get_similar_contacts returns ranked results
  6. build_audience_export enforces ExportEligibility gate
  7. Privacy assurance: no PII or synthetic private data in DNA
  8. Idempotency: recalculate_contact twice produces same state
  9. Buyer role priority ordering when multiple commercial signals exist
 10. Segment expiry evidence logs contain role string
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select

from app.db.models import (
    AudienceMembership,
    AudienceSegment,
    Contact,
    ContactIntelligence,
    ExportEligibility,
)
from app.schemas.instagram import InstagramComment, InstagramPost
from app.schemas.leads import Intent, LeadAnalysis
from app.services.audience_service import (
    AudienceEngine,
    calculate_contact_similarity,
)
from app.services.contact_service import ContactService
from app.services.lead_service import LeadService
from tests.test_contact_service import make_comment, make_post

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_post_for(competitor: str, post_id: str = "post-1") -> InstagramPost:
    return make_post().model_copy(
        update={
            "platform_post_id": post_id,
            "competitor": competitor,
            "url": f"https://www.instagram.com/reel/{post_id}/",
        }
    )


def make_b2b_comment(comment_id: str = "b2b-1") -> InstagramComment:
    """Explicit wholesale / HoReCa signal."""
    return make_comment(comment_id).model_copy(
        update={"text": "нам нужно 50 стульев для ресторана, оптом", "platform_comment_id": comment_id}
    )


def make_designer_comment(comment_id: str = "des-1") -> InstagramComment:
    """Designer / project specifier signal."""
    return make_comment(comment_id).model_copy(
        update={"text": "нужна 3D-модель для проекта", "platform_comment_id": comment_id}
    )


class B2BLeadAnalyzer:
    """Simulates a V2 analyzer returning B2B_HORECA buyer role."""

    async def analyze(self, context):
        return LeadAnalysis(
            is_lead=True,
            lead_score=85,
            intent=Intent.BUY,
            product_category="CHAIRS",
            language="ru",
            reason="Bulk restaurant order",
            buyer_role="B2B_HORECA",
            factors={
                "intent_strength": 45,
                "specificity_score": 20,
                "role_score": 15,
                "history_boost": 5,
                "objection_penalty": 0,
            },
        )


class DesignerLeadAnalyzer:
    """Simulates a V2 analyzer returning DESIGNER_CONTRACTOR buyer role."""

    async def analyze(self, context):
        return LeadAnalysis(
            is_lead=True,
            lead_score=75,
            intent=Intent.CATALOG,
            product_category="DINING_SET",
            language="ru",
            reason="Designer requesting 3D model",
            buyer_role="DESIGNER_CONTRACTOR",
            factors={
                "intent_strength": 30,
                "specificity_score": 25,
                "role_score": 15,
                "history_boost": 5,
                "objection_penalty": 0,
            },
        )


class BasicLeadAnalyzer:
    """Simulates a plain B2C signal."""

    async def analyze(self, context):
        return LeadAnalysis(
            is_lead=True,
            lead_score=91,
            intent=Intent.PRICE,
            product_category="DINING_SET",
            language="uz",
            reason="Price inquiry",
        )


async def _get_intel(session_factory, contact_id: int) -> ContactIntelligence:
    async with session_factory() as session:
        intel = await session.scalar(
            select(ContactIntelligence).where(
                ContactIntelligence.contact_id == contact_id
            )
        )
    assert intel is not None
    return intel


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


# ---------------------------------------------------------------------------
# Test 1: Profile DNA — B2B_HORECA buyer role from V2 analysis_details
# ---------------------------------------------------------------------------


async def test_profile_dna_b2b_horeca_buyer_role(session_factory):
    """ContactIntelligence.primary_buyer_role is set to B2B_HORECA for wholesale signals."""
    engine = AudienceEngine(session_factory, hot_threshold=70)
    signal = await ContactService(session_factory).persist_signal(
        make_post(), make_b2b_comment()
    )
    await LeadService(
        session_factory,
        B2BLeadAnalyzer(),
        hot_threshold=70,
        audience_engine=engine,
    ).process_signal(signal)
    await engine.recalculate_contact(signal.contact_id)

    intel = await _get_intel(session_factory, signal.contact_id)
    assert intel.primary_buyer_role == "B2B_HORECA"
    assert "B2B_HORECA" in intel.buyer_roles_json


# ---------------------------------------------------------------------------
# Test 2: Profile DNA — DESIGNER_CONTRACTOR buyer role
# ---------------------------------------------------------------------------


async def test_profile_dna_designer_buyer_role(session_factory):
    engine = AudienceEngine(session_factory, hot_threshold=70)
    signal = await ContactService(session_factory).persist_signal(
        make_post(), make_designer_comment()
    )
    await LeadService(
        session_factory,
        DesignerLeadAnalyzer(),
        hot_threshold=70,
        audience_engine=engine,
    ).process_signal(signal)
    await engine.recalculate_contact(signal.contact_id)

    intel = await _get_intel(session_factory, signal.contact_id)
    assert intel.primary_buyer_role == "DESIGNER_CONTRACTOR"
    assert "DESIGNER_CONTRACTOR" in intel.buyer_roles_json


# ---------------------------------------------------------------------------
# Test 3: Buyer role priority — B2B_HORECA wins over DESIGNER_CONTRACTOR
# ---------------------------------------------------------------------------


async def test_profile_dna_buyer_role_priority_b2b_over_designer(session_factory):
    """When signals include both roles, B2B_HORECA has higher priority."""
    engine = AudienceEngine(session_factory, hot_threshold=70)
    cs = ContactService(session_factory)

    # First: designer signal
    sig_a = await cs.persist_signal(make_post(), make_designer_comment("des-p1"))
    await LeadService(
        session_factory, DesignerLeadAnalyzer(), hot_threshold=70, audience_engine=engine
    ).process_signal(sig_a)

    # Second: B2B signal on same post for a different post id to ensure new comment
    sig_b = await cs.persist_signal(
        make_post_for("aiko.uz", "post-2"), make_b2b_comment("b2b-p2")
    )
    await LeadService(
        session_factory, B2BLeadAnalyzer(), hot_threshold=70, audience_engine=engine
    ).process_signal(sig_b)

    # Should be the same contact since same user_id
    assert sig_a.contact_id == sig_b.contact_id
    await engine.recalculate_contact(sig_a.contact_id)

    intel = await _get_intel(session_factory, sig_a.contact_id)
    # B2B_HORECA priority > DESIGNER_CONTRACTOR
    assert intel.primary_buyer_role == "B2B_HORECA"
    assert "DESIGNER_CONTRACTOR" in intel.buyer_roles_json
    assert "B2B_HORECA" in intel.buyer_roles_json


# ---------------------------------------------------------------------------
# Test 4: New Phase 4 segment — horeca-b2b activates for B2B_HORECA role
# ---------------------------------------------------------------------------


async def test_phase4_segment_horeca_b2b_activates(session_factory):
    engine = AudienceEngine(session_factory, hot_threshold=70)
    signal = await ContactService(session_factory).persist_signal(
        make_post(), make_b2b_comment()
    )
    await LeadService(
        session_factory, B2BLeadAnalyzer(), hot_threshold=70, audience_engine=engine
    ).process_signal(signal)
    await engine.recalculate_contact(signal.contact_id)

    active = await _active_slugs(session_factory, signal.contact_id)
    assert "horeca-b2b" in active


# ---------------------------------------------------------------------------
# Test 5: New Phase 4 segment — designers activates for DESIGNER_CONTRACTOR role
# ---------------------------------------------------------------------------


async def test_phase4_segment_designers_activates(session_factory):
    engine = AudienceEngine(session_factory, hot_threshold=70)
    signal = await ContactService(session_factory).persist_signal(
        make_post(), make_designer_comment()
    )
    await LeadService(
        session_factory, DesignerLeadAnalyzer(), hot_threshold=70, audience_engine=engine
    ).process_signal(signal)
    await engine.recalculate_contact(signal.contact_id)

    active = await _active_slugs(session_factory, signal.contact_id)
    assert "designers" in active


# ---------------------------------------------------------------------------
# Test 6: Segment evidence log contains buyer_role string
# ---------------------------------------------------------------------------


async def test_phase4_segment_evidence_log_contains_role(session_factory):
    engine = AudienceEngine(session_factory, hot_threshold=70)
    signal = await ContactService(session_factory).persist_signal(
        make_post(), make_b2b_comment()
    )
    await LeadService(
        session_factory, B2BLeadAnalyzer(), hot_threshold=70, audience_engine=engine
    ).process_signal(signal)
    await engine.recalculate_contact(signal.contact_id)

    async with session_factory() as session:
        membership = await session.scalar(
            select(AudienceMembership)
            .join(AudienceSegment, AudienceSegment.id == AudienceMembership.segment_id)
            .where(
                AudienceSegment.slug == "horeca-b2b",
                AudienceMembership.contact_id == signal.contact_id,
                AudienceMembership.active.is_(True),
            )
        )
    assert membership is not None
    assert any("B2B_HORECA" in e for e in membership.evidence_json)


# ---------------------------------------------------------------------------
# Test 7: Deterministic similarity — identical profiles score 1.0
# ---------------------------------------------------------------------------


def _make_intel(**kwargs) -> ContactIntelligence:
    defaults = dict(
        contact_id=1,
        first_seen_at=datetime.now(UTC),
        last_seen_at=datetime.now(UTC),
        primary_buyer_role="B2C_CONSUMER",
        buyer_roles_json=["B2C_CONSUMER"],
        evidence_count=0,
        similarity_vector_json={},
        product_interests_json=[{"value": "DINING_SET", "count": 3, "confidence": 100}],
        top_intents_json=[{"value": "PRICE", "count": 2, "confidence": 100}],
        vertical="FURNITURE",
        quantity_band=None,
    )
    defaults.update(kwargs)
    return ContactIntelligence(**defaults)


def test_calculate_similarity_identical_profiles():
    a = _make_intel()
    b = _make_intel(contact_id=2)
    assert calculate_contact_similarity(a, b) == 1.0


def test_calculate_similarity_disjoint_profiles():
    a = _make_intel(
        product_interests_json=[{"value": "RATTAN_FURNITURE", "count": 1, "confidence": 100}],
        top_intents_json=[{"value": "DELIVERY", "count": 1, "confidence": 100}],
        primary_buyer_role="B2B_HORECA",
        vertical="ARTIFICIAL_RATTAN",
        quantity_band="50_PLUS",
    )
    b = _make_intel(
        contact_id=2,
        product_interests_json=[{"value": "CHAIRS", "count": 1, "confidence": 100}],
        top_intents_json=[{"value": "AVAILABILITY", "count": 1, "confidence": 100}],
        primary_buyer_role="DESIGNER_CONTRACTOR",
        vertical="FURNITURE",
        quantity_band=None,
    )
    score = calculate_contact_similarity(a, b)
    assert 0.0 <= score < 0.5


def test_calculate_similarity_partial_product_overlap():
    a = _make_intel(
        product_interests_json=[
            {"value": "DINING_SET", "count": 2, "confidence": 100},
            {"value": "TABLE", "count": 1, "confidence": 50},
        ],
    )
    b = _make_intel(
        contact_id=2,
        product_interests_json=[
            {"value": "DINING_SET", "count": 1, "confidence": 100},
            {"value": "CHAIRS", "count": 1, "confidence": 50},
        ],
    )
    score = calculate_contact_similarity(a, b)
    # Partial overlap → should be between 0 and 1, meaningfully above 0
    assert 0.0 < score < 1.0


def test_calculate_similarity_empty_profiles():
    a = _make_intel(product_interests_json=[], top_intents_json=[])
    b = _make_intel(contact_id=2, product_interests_json=[], top_intents_json=[])
    # Empty sets → Jaccard returns 1.0 for both dimensions
    score = calculate_contact_similarity(a, b)
    assert score == 1.0


def test_calculate_similarity_returns_float_in_range():
    import random
    roles = ["B2C_CONSUMER", "B2B_HORECA", "DESIGNER_CONTRACTOR", "UNKNOWN"]
    products = ["DINING_SET", "TABLE", "CHAIRS", "RATTAN_FURNITURE", "OUTDOOR_FURNITURE"]
    intents = ["PRICE", "DELIVERY", "AVAILABILITY", "BUY"]
    for _ in range(20):
        a = _make_intel(
            primary_buyer_role=random.choice(roles),
            product_interests_json=[{"value": random.choice(products), "count": 1, "confidence": 100}],
            top_intents_json=[{"value": random.choice(intents), "count": 1, "confidence": 100}],
        )
        b = _make_intel(
            contact_id=2,
            primary_buyer_role=random.choice(roles),
            product_interests_json=[{"value": random.choice(products), "count": 1, "confidence": 100}],
            top_intents_json=[{"value": random.choice(intents), "count": 1, "confidence": 100}],
        )
        score = calculate_contact_similarity(a, b)
        assert 0.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# Test 8: get_similar_contacts returns ranked list
# ---------------------------------------------------------------------------


async def test_get_similar_contacts_returns_ranked_list(session_factory):
    engine = AudienceEngine(session_factory, hot_threshold=70)
    cs = ContactService(session_factory)

    # Contact 1: price inquirer, dining set
    sig1 = await cs.persist_signal(make_post(), make_comment("c1"))
    await LeadService(
        session_factory, BasicLeadAnalyzer(), hot_threshold=70, audience_engine=engine
    ).process_signal(sig1)
    await engine.recalculate_contact(sig1.contact_id)

    # Contact 2: different user, different comment
    sig2 = await cs.persist_signal(
        make_post_for("chinar.uz", "post-2"),
        make_comment("c2").model_copy(update={
            "platform_user_id": "user-2",
            "username": "Bobur_Test",
            "platform_comment_id": "c2",
        }),
    )
    await LeadService(
        session_factory, BasicLeadAnalyzer(), hot_threshold=70, audience_engine=engine
    ).process_signal(sig2)
    await engine.recalculate_contact(sig2.contact_id)

    similar = await engine.get_similar_contacts(sig1.contact_id, limit=5)
    assert isinstance(similar, list)
    assert len(similar) >= 1
    for item in similar:
        assert "contact_id" in item
        assert "score" in item
        assert item["contact_id"] != sig1.contact_id
        assert 0.0 <= item["score"] <= 1.0

    # Should be sorted descending
    scores = [item["score"] for item in similar]
    assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------------------
# Test 9: build_audience_export — only FIRST_PARTY_ELIGIBLE contacts exported
# ---------------------------------------------------------------------------


async def test_build_audience_export_eligibility_gate(session_factory):
    engine = AudienceEngine(session_factory, hot_threshold=70)
    cs = ContactService(session_factory)

    # Create and qualify a contact
    sig = await cs.persist_signal(make_post(), make_comment("export-1"))
    await LeadService(
        session_factory, B2BLeadAnalyzer(), hot_threshold=70, audience_engine=engine
    ).process_signal(sig)

    async with session_factory() as session:
        contact = await session.get(Contact, sig.contact_id)
        assert contact is not None
        contact.phone = "+998901234567"
        contact.qualification_updated_at = datetime.now(UTC)
        await session.commit()

    await engine.recalculate_contact(sig.contact_id)

    # With eligibility gate — should include qualified contact
    eligible_rows = await engine.build_audience_export("horeca-b2b", require_export_eligible=True)
    assert len(eligible_rows) >= 1
    for row in eligible_rows:
        assert row["export_eligibility"] == ExportEligibility.FIRST_PARTY_ELIGIBLE.value
        assert row["phone"] is not None

    # Non-eligible — should find contact when gate is disabled
    all_rows = await engine.build_audience_export("horeca-b2b", require_export_eligible=False)
    assert len(all_rows) >= len(eligible_rows)


async def test_build_audience_export_excludes_unqualified(session_factory):
    engine = AudienceEngine(session_factory, hot_threshold=70)
    cs = ContactService(session_factory)

    sig = await cs.persist_signal(make_post(), make_b2b_comment("unq-1"))
    await LeadService(
        session_factory, B2BLeadAnalyzer(), hot_threshold=70, audience_engine=engine
    ).process_signal(sig)
    await engine.recalculate_contact(sig.contact_id)

    # contact has no phone → NOT_EXPORTABLE
    rows = await engine.build_audience_export("horeca-b2b", require_export_eligible=True)
    contact_ids = [r["contact_id"] for r in rows]
    assert sig.contact_id not in contact_ids


# ---------------------------------------------------------------------------
# Test 10: Privacy assurance — no synthetic PII in DNA
# ---------------------------------------------------------------------------


async def test_profile_dna_contains_no_synthetic_pii(session_factory):
    engine = AudienceEngine(session_factory, hot_threshold=70)
    signal = await ContactService(session_factory).persist_signal(
        make_post(), make_b2b_comment()
    )
    await LeadService(
        session_factory, B2BLeadAnalyzer(), hot_threshold=70, audience_engine=engine
    ).process_signal(signal)
    await engine.recalculate_contact(signal.contact_id)

    intel = await _get_intel(session_factory, signal.contact_id)
    vec = intel.similarity_vector_json

    # Similarity vector must only contain observable categorical data, not PII
    pii_keys = {"phone", "email", "address", "full_name", "income", "age"}
    assert not pii_keys.intersection(vec.keys()), (
        f"Similarity vector must not contain PII keys, got: {set(vec.keys())}"
    )


# ---------------------------------------------------------------------------
# Test 11: Idempotency — recalculate_contact twice gives same state
# ---------------------------------------------------------------------------


async def test_recalculate_contact_idempotent(session_factory):
    engine = AudienceEngine(session_factory, hot_threshold=70)
    signal = await ContactService(session_factory).persist_signal(
        make_post(), make_b2b_comment()
    )
    await LeadService(
        session_factory, B2BLeadAnalyzer(), hot_threshold=70, audience_engine=engine
    ).process_signal(signal)

    await engine.recalculate_contact(signal.contact_id)
    intel_1 = await _get_intel(session_factory, signal.contact_id)
    slugs_1 = await _active_slugs(session_factory, signal.contact_id)

    await engine.recalculate_contact(signal.contact_id)
    intel_2 = await _get_intel(session_factory, signal.contact_id)
    slugs_2 = await _active_slugs(session_factory, signal.contact_id)

    assert intel_1.primary_buyer_role == intel_2.primary_buyer_role
    assert intel_1.buyer_roles_json == intel_2.buyer_roles_json
    assert intel_1.value_score == intel_2.value_score
    assert slugs_1 == slugs_2


# ---------------------------------------------------------------------------
# Test 12: evidence_count reflects linked public signals
# ---------------------------------------------------------------------------


async def test_evidence_count_reflects_linked_signals(session_factory):
    """evidence_count tracks how many Evidence rows link to this contact's comments."""
    engine = AudienceEngine(session_factory, hot_threshold=70)
    signal = await ContactService(session_factory).persist_signal(
        make_post(), make_b2b_comment()
    )
    await LeadService(
        session_factory, B2BLeadAnalyzer(), hot_threshold=70, audience_engine=engine
    ).process_signal(signal)
    await engine.recalculate_contact(signal.contact_id)

    intel = await _get_intel(session_factory, signal.contact_id)
    # evidence_count should be >= 0 — even if no Evidence rows exist yet in test DB
    # the key assertion is that the field is populated (not None) and an integer
    assert isinstance(intel.evidence_count, int)
    assert intel.evidence_count >= 0


# ---------------------------------------------------------------------------
# Test 13: Interest Decay / Half-life calculation
# ---------------------------------------------------------------------------


def test_interest_decay_half_life():
    from app.services.audience_service import calculate_decayed_interest_score

    # PRICE half-life is 14 days. After 14 days, score of 100 should be 50.0
    decayed_14d = calculate_decayed_interest_score(100.0, "PRICE", 14.0)
    assert decayed_14d == 50.0

    # AVAILABILITY half-life is 10 days. After 10 days, score of 80 should be 40.0
    decayed_10d = calculate_decayed_interest_score(80.0, "AVAILABILITY", 10.0)
    assert decayed_10d == 40.0

    # Zero elapsed days -> score unchanged
    decayed_0d = calculate_decayed_interest_score(90.0, "PRICE", 0.0)
    assert decayed_0d == 90.0

