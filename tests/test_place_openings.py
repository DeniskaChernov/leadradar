"""
test_place_openings.py — Master Phase 10 test suite

Tests:
  1. Venue opening signal detection (restaurants, cafes, hotels, timeline)
  2. Idempotent signal storage
  3. Manager review queue transition (VERIFIED / REJECTED)
  4. Invalid review decision validation
  5. Web API endpoints /api/openings and /api/openings/{id}/review
"""

from __future__ import annotations

import pytest

from app.services.place_opening_service import PlaceOpeningService


def test_detect_opening_signals():
    # Restaurant opening
    s1 = PlaceOpeningService.detect_opening_signals("Мы открываем новый ресторан в Ташкенте, нужны стулья!")
    assert s1 is not None
    assert s1["place_type"] == "RESTAURANT"
    assert s1["confidence"] >= 80

    # Cafe opening
    s2 = PlaceOpeningService.detect_opening_signals("янги кафе очиляпти на следующей неделе")
    assert s2 is not None
    assert s2["place_type"] == "CAFE"
    assert s2["opening_timeline"] == "НА СЛЕДУЮЩЕЙ НЕДЕЛЕ"

    # Non-opening comment
    s3 = PlaceOpeningService.detect_opening_signals("сколько стоит один стул?")
    assert s3 is None


async def test_store_and_review_opening_signal(session_factory):
    service = PlaceOpeningService(session_factory)

    # 1. Store
    sig1 = await service.store_opening_signal(
        place_name="Ресторан Chayxona #1",
        place_type="RESTAURANT",
        city="Tashkent",
        contact_id=1,
        confidence=85,
    )
    assert sig1.id is not None
    assert sig1.review_status == "PENDING_REVIEW"

    # 2. Duplicate store returns existing instance
    sig2 = await service.store_opening_signal(
        place_name="Ресторан Chayxona #1",
        place_type="RESTAURANT",
        city="Tashkent",
        contact_id=1,
        confidence=85,
    )
    assert sig2.id == sig1.id

    # 3. Check review queue
    queue = await service.get_review_queue()
    assert any(item.id == sig1.id for item in queue)

    # 4. Review decision -> VERIFIED
    reviewed = await service.review_opening_signal(sig1.id, manager_id=7, decision="VERIFIED")
    assert reviewed.review_status == "VERIFIED"
    assert reviewed.reviewed_by_manager_id == 7

    # 5. Check queue after review
    queue_after = await service.get_review_queue()
    assert not any(item.id == sig1.id for item in queue_after)


async def test_invalid_review_decision_raises(session_factory):
    service = PlaceOpeningService(session_factory)
    sig = await service.store_opening_signal(
        place_name="Отель Wyndham",
        place_type="HOTEL",
    )
    with pytest.raises(ValueError, match="Invalid review decision"):
        await service.review_opening_signal(sig.id, manager_id=1, decision="INVALID_DECISION")


async def test_place_openings_api_endpoints(session_factory):
    from httpx import ASGITransport, AsyncClient

    from app.config import Settings
    from app.services.crm_service import CRMService
    from app.services.lead_workflow_service import LeadWorkflowService
    from app.services.monitor_controller import MonitorController
    from app.web.app import build_web_app
    from app.web.queries import WebQueryService

    settings = Settings(web_auth_enabled=False)
    queries = WebQueryService(session_factory, hot_threshold=70)
    crm = CRMService(session_factory)
    workflow = LeadWorkflowService(session_factory, hot_threshold=70)
    controller = MonitorController(None)  # type: ignore[arg-type]

    app = build_web_app(
        settings=settings,
        queries=queries,
        workflow=workflow,
        controller=controller,
        crm=crm,
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        # Store opening via service first
        service = PlaceOpeningService(session_factory)
        sig = await service.store_opening_signal(
            place_name="Кафе Bon!", place_type="CAFE"
        )

        # GET review queue
        r1 = await client.get("/api/openings")
        assert r1.status_code == 200
        d1 = r1.json()
        assert d1["ok"] is True
        assert any(item["id"] == sig.id for item in d1["queue"])

        # The manager page uses the shared confirmed-action client instead of
        # a second inline fetch implementation.
        page = await client.get("/openings")
        assert page.status_code == 200
        assert f'data-api-action="/api/openings/{sig.id}/review"' in page.text
        assert 'data-payload=\'{"decision":"VERIFIED"}\'' in page.text
        assert "reviewOpening(" not in page.text

        # POST review -> VERIFIED
        r2 = await client.post(f"/api/openings/{sig.id}/review", json={"decision": "VERIFIED"})
        assert r2.status_code == 200
        d2 = r2.json()
        assert d2["ok"] is True
        assert d2["review_status"] == "VERIFIED"
