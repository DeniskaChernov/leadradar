from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from app.db.models import (
    Comment,
    Competitor,
    Contact,
    ContactEvent,
    ContactEventType,
    Evidence,
    Lead,
    Post,
    PublicSignal,
)
from app.schemas.leads import BuyerRole, Intent
from app.services.ai_service import (
    LeadAnalysisContext,
    RuleBasedLeadAnalyzer,
    ValidatedPreviousSignal,
)
from app.services.lead_service import LeadService


def test_intelligence_v2_golden_dataset_calibration():
    fixture_path = Path(__file__).resolve().parent.parent / "fixtures" / "golden_lead_calibration.json"
    with fixture_path.open("r", encoding="utf-8") as f:
        cases = json.load(f)

    analyzer = RuleBasedLeadAnalyzer()
    passed = 0

    for case in cases:
        context = LeadAnalysisContext(
            competitor="test_furniture",
            post_caption=case.get("post_caption", ""),
            comment=case["comment"],
            username="test_user",
            previous_signals=[],
            previous_interests=[],
        )
        analysis = analyzer.classify(context)
        if case.get("defer_to_openai"):
            assert analysis is None, case["id"]
            passed += 1
            continue
        if analysis is None:
            analysis = analyzer._result(
                False,
                30,
                Intent.OTHER,
                None,
                case.get("language", "ru"),
                "Unclassified",
                context,
            )

        assert analysis.intelligence_version == "3.0", f"Case {case['id']} version mismatch"
        assert analysis.is_lead == case["expected_is_lead"], (
            f"Case {case['id']} failed is_lead check: got {analysis.is_lead}, expected {case['expected_is_lead']}"
        )
        if "expected_intent" in case:
            assert analysis.intent.value == case["expected_intent"], (
                f"Case {case['id']} failed intent: got {analysis.intent.value}, expected {case['expected_intent']}"
            )
        if "expected_buyer_role" in case:
            assert analysis.buyer_role.value == case["expected_buyer_role"], (
                f"Case {case['id']} failed role: got {analysis.buyer_role.value}, expected {case['expected_buyer_role']}"
            )
        if "min_score" in case:
            assert analysis.lead_score >= case["min_score"], (
                f"Case {case['id']} failed min_score: got {analysis.lead_score}, expected >= {case['min_score']}"
            )
        if "max_score" in case:
            assert analysis.lead_score <= case["max_score"], (
                f"Case {case['id']} failed max_score: got {analysis.lead_score}, expected <= {case['max_score']}"
            )

        # Factor validation
        factors = analysis.factors
        assert "intent_score" in factors
        assert "activity_score" in factors
        assert "specificity_score" in factors
        assert "role_score" in factors
        assert "history_boost" in factors
        assert "confidence_score" in factors
        assert "priority_score" in factors

        passed += 1

    assert passed == len(cases)
    assert passed >= 25


def test_intelligence_v2_role_and_factors_breakdown():
    analyzer = RuleBasedLeadAnalyzer()

    # B2B HoReCa
    b2b_ctx = LeadAnalysisContext(
        competitor="aiko",
        post_caption="Садовая мебель",
        comment="Нужны столы для ресторана, 20 штук",
        username="restoran_owner",
        previous_signals=[],
        previous_interests=[],
    )
    b2b_res = analyzer.classify(b2b_ctx)
    assert b2b_res is not None
    assert b2b_res.buyer_role == BuyerRole.B2B_HORECA
    assert b2b_res.factors["role_score"] == 90
    assert b2b_res.factors["intent_strength"] >= 90

    # Designer
    designer_ctx = LeadAnalysisContext(
        competitor="aiko",
        post_caption="Премиум столы",
        comment="Ищу мебель для дизайн-проекта, пришлите 3D модель",
        username="designer_pro",
        previous_signals=[],
        previous_interests=[],
    )
    designer_res = analyzer.classify(designer_ctx)
    assert designer_res is not None
    assert designer_res.buyer_role == BuyerRole.DESIGNER_CONTRACTOR
    assert designer_res.factors["role_score"] == 85

    # Job seeker
    job_ctx = LeadAnalysisContext(
        competitor="aiko",
        post_caption="Мы растем",
        comment="Работа нужна, вакансии есть?",
        username="job_applicant",
        previous_signals=[],
        previous_interests=[],
    )
    job_res = analyzer.classify(job_ctx)
    assert job_res is not None
    assert job_res.is_lead is False
    assert job_res.buyer_role == BuyerRole.JOB_SEEKER
    assert job_res.factors["role_score"] == 5


def test_intelligence_v2_history_and_comparison_boost():
    analyzer = RuleBasedLeadAnalyzer()

    # Context with prior inquiries across 2 different competitors
    prior = [
        ValidatedPreviousSignal(
            lead_id=1,
            public_signal_id=1,
            evidence_ids=[1],
            competitor_id=1,
            competitor="competitor_a",
            intent="PRICE",
            product_family="TABLE",
            buyer_role="B2C_CONSUMER",
            commercial_quality="MEDIUM_COMMERCIAL",
            priority_score=72,
            confidence=85,
            observed_at="2026-08-20T10:00:00Z",
            vertical="FURNITURE",
        ),
        ValidatedPreviousSignal(
            lead_id=2,
            public_signal_id=2,
            evidence_ids=[2],
            competitor_id=2,
            competitor="competitor_b",
            intent="AVAILABILITY",
            product_family="CHAIRS",
            buyer_role="B2C_CONSUMER",
            commercial_quality="MEDIUM_COMMERCIAL",
            priority_score=78,
            confidence=88,
            observed_at="2026-08-22T10:00:00Z",
            vertical="FURNITURE",
        ),
    ]
    ctx = LeadAnalysisContext(
        competitor="competitor_c",
        post_caption="Обеденные зоны",
        comment="Какая цена на обеденный комплект?",
        username="active_buyer",
        previous_signals=prior,
        previous_interests=["CHAIRS"],
    )
    res = analyzer.classify(ctx)
    assert res is not None
    assert res.factors["history_boost"] > 0
    # Cross competitor comparison gives extra points
    assert res.factors["history_boost"] >= 9


async def test_lead_service_links_evidence_ids_in_v2_analysis(session_factory):
    async with session_factory() as session:
        competitor = Competitor(
            handle="aiko",
            normalized_handle="aiko",
            display_name="Aiko",
            website_url="https://instagram.com/aiko",
        )
        session.add(competitor)
        await session.flush()

        contact = Contact(
            platform="instagram",
            username="evidence_buyer",
            normalized_username="evidence_buyer",
            profile_url="https://instagram.com/evidence_buyer",
        )
        session.add(contact)
        await session.flush()

        post = Post(
            competitor_id=competitor.id,
            platform_post_id="post_ev_1",
            url="https://instagram.com/p/ev1",
            caption="Обеденные столы из ротанга",
        )
        session.add(post)
        await session.flush()

        comment = Comment(
            platform="instagram",
            platform_comment_id="comment_ev_1",
            contact_id=contact.id,
            post_id=post.id,
            competitor_id=competitor.id,
            text="Хочу купить обеденный комплект со столом",
        )
        session.add(comment)
        await session.flush()

        signal = PublicSignal(
            comment_id=comment.id,
            contact_id=contact.id,
            competitor_id=competitor.id,
            platform="instagram",
            external_id="comment_ev_1",
            dedupe_key="instagram:COMMENT:comment_ev_1",
            text=comment.text,
        )
        session.add(signal)
        await session.flush()

        evidence = Evidence(
            evidence_key="instagram:COMMENT:comment_ev_1:text",
            public_signal_id=signal.id,
            source_type="COMMENT",
            text=comment.text,
            strength=90,
            confidence=100,
            observed_at=datetime.now(UTC),
        )
        session.add(evidence)
        await session.commit()
        evidence_id = evidence.id
        comment_id = comment.id

    service = LeadService(session_factory, RuleBasedLeadAnalyzer(), hot_threshold=70)
    lead = await service._create_pending(
        type("SignalStub", (), {
            "comment_id": comment_id,
            "contact_id": contact.id,
            "competitor_id": competitor.id,
            "is_baseline": False,
            "created": True,
            "public_signal_id": signal.id,
        })()
    )

    processed = await service.analyze_lead(lead.lead_id)
    assert processed.score >= 90
    assert processed.is_hot is True

    async with session_factory() as session:
        stored_lead = await session.get(Lead, lead.lead_id)
        assert stored_lead is not None
        details = stored_lead.analysis_details
        assert details is not None
        assert details["intelligence_version"] == "3.0"
        assert evidence_id in details["evidence_ids"]
        assert details["buyer_role"] == BuyerRole.B2C_CONSUMER.value
        assert "factors" in details
        assert details["factors"]["intent_strength"] >= 90

        # Check contact event payload
        events = (
            await session.scalars(
                select(ContactEvent)
                .where(
                    ContactEvent.contact_id == contact.id,
                    ContactEvent.event_type == ContactEventType.LEAD_SCORE_CHANGED,
                )
            )
        ).all()
        assert len(events) == 1
        payload = events[0].payload_json
        assert payload["intelligence_version"] == "3.0"
        assert evidence_id in payload["evidence_ids"]
        assert payload["buyer_role"] == BuyerRole.B2C_CONSUMER.value
