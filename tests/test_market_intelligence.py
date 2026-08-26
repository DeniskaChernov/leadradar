from __future__ import annotations

from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.config import Settings
from app.data.competitor_catalog import MARKET_CANDIDATES, MONITORED_COMPETITORS
from app.db.models import Competitor, MarketCandidate
from app.services.lead_workflow_service import LeadWorkflowService
from app.services.market_intelligence_service import MarketIntelligenceService
from app.services.monitor_controller import MonitorController
from app.web.app import build_web_app
from app.web.queries import WebQueryService


class FakeMonitor:
    provider = None


async def test_market_catalog_sync_is_idempotent_and_safe(session_factory):
    service = MarketIntelligenceService(session_factory)

    first = await service.sync_catalog()
    second = await service.sync_catalog()

    assert first["created_competitors"] == len(MONITORED_COMPETITORS)
    assert first["created_candidates"] == len(MARKET_CANDIDATES)
    assert second == {"created_competitors": 0, "created_candidates": 0}

    async with session_factory() as session:
        competitor_count = int(await session.scalar(select(func.count(Competitor.id))) or 0)
        candidate_count = int(await session.scalar(select(func.count(MarketCandidate.id))) or 0)
        active_handles = set(
            await session.scalars(select(Competitor.normalized_handle).where(Competitor.active.is_(True)))
        )

    assert competitor_count == len(MONITORED_COMPETITORS)
    assert candidate_count == len(MARKET_CANDIDATES)
    # Market expansion must never silently turn every new account into paid monitoring.
    assert active_handles == {seed.handle for seed in MONITORED_COMPETITORS if seed.active_by_default}


async def test_catalog_sync_preserves_user_monitoring_choices(session_factory):
    service = MarketIntelligenceService(session_factory)
    await service.sync_catalog()

    async with session_factory() as session:
        aiko = await session.scalar(select(Competitor).where(Competitor.normalized_handle == "aiko.uz"))
        assert aiko is not None
        aiko.active = False
        aiko.tier = "C"
        aiko.poll_interval_seconds = 1800
        await session.commit()

    await service.sync_catalog()

    async with session_factory() as session:
        aiko = await session.scalar(select(Competitor).where(Competitor.normalized_handle == "aiko.uz"))
        assert aiko is not None
        assert aiko.active is False
        assert aiko.tier == "C"
        assert aiko.poll_interval_seconds == 1800


async def test_market_candidate_can_be_promoted_paused(session_factory):
    service = MarketIntelligenceService(session_factory)
    await service.sync_catalog()
    async with session_factory() as session:
        candidate = await session.scalar(
            select(MarketCandidate).where(MarketCandidate.display_name == "Lazuno Ok")
        )
        assert candidate is not None
        candidate_id = candidate.id

    competitor = await service.promote_candidate(candidate_id, handle="lazuno.ok", active=False)

    assert competitor.normalized_handle == "lazuno.ok"
    assert competitor.active is False
    async with session_factory() as session:
        candidate = await session.get(MarketCandidate, candidate_id)
        assert candidate is not None
        assert candidate.status == "PROMOTED"


async def test_market_pages_render_and_candidate_promotion_api(session_factory):
    service = MarketIntelligenceService(session_factory)
    await service.sync_catalog()
    settings = Settings(_env_file=None, web_enabled=True, instagram_provider="replay")
    app = build_web_app(
        settings,
        WebQueryService(session_factory, hot_threshold=70),
        LeadWorkflowService(session_factory, hot_threshold=70),
        MonitorController(FakeMonitor()),  # type: ignore[arg-type]
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        competitors = await client.get("/competitors")
        roadmap = await client.get("/roadmap")
        async with session_factory() as session:
            candidate = await session.scalar(
                select(MarketCandidate).where(MarketCandidate.display_name == "Rotan")
            )
            assert candidate is not None
            candidate_id = candidate.id
        promoted = await client.post(
            f"/api/market-candidates/{candidate_id}/promote",
            json={"handle": "rotan.test", "active": False},
        )

    assert competitors.status_code == 200
    assert "Мы больше не ограничены AIKO" in competitors.text
    assert "Lazuno Ok" in competitors.text
    assert roadmap.status_code == 200
    assert "Стадия 3 из 7" in roadmap.text
    assert promoted.status_code == 200
    assert promoted.json()["ok"] is True
