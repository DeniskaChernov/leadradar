from __future__ import annotations

import asyncio

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
    assert second == {
        "created_competitors": 0,
        "created_candidates": 0,
        "promoted_candidates": 0,
    }

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
            select(MarketCandidate).where(MarketCandidate.display_name == "Rotan")
        )
        assert candidate is not None
        candidate_id = candidate.id

    competitor = await service.promote_candidate(candidate_id, handle="rotan.uz", active=False)

    assert competitor.normalized_handle == "rotan.uz"
    assert competitor.active is False
    async with session_factory() as session:
        candidate = await session.get(MarketCandidate, candidate_id)
        assert candidate is not None
        assert candidate.status == "PROMOTED"


async def test_concurrent_candidate_promotion_creates_one_competitor(
    file_session_factory,
):
    first = MarketIntelligenceService(file_session_factory)
    second = MarketIntelligenceService(file_session_factory)
    await first.sync_catalog()
    async with file_session_factory() as session:
        candidate = await session.scalar(
            select(MarketCandidate).where(MarketCandidate.display_name == "Rotan")
        )
        assert candidate is not None
        candidate_id = candidate.id

    promoted = await asyncio.gather(
        first.promote_candidate(candidate_id, handle="rotan.race", active=False),
        second.promote_candidate(candidate_id, handle="rotan.race", active=False),
    )

    assert promoted[0].id == promoted[1].id
    async with file_session_factory() as session:
        count = await session.scalar(
            select(func.count(Competitor.id)).where(
                Competitor.normalized_handle == "rotan.race"
            )
        )
    assert count == 1


async def test_market_pages_render_and_candidate_promotion_api(session_factory):
    service = MarketIntelligenceService(session_factory)
    await service.sync_catalog()
    settings = Settings(_env_file=None, web_enabled=True, instagram_provider="replay", web_manager_id=1001)
    app = build_web_app(
        settings,
        WebQueryService(session_factory, hot_threshold=70),
        LeadWorkflowService(session_factory, hot_threshold=70),
        MonitorController(FakeMonitor()),  # type: ignore[arg-type]
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        competitors = await client.get("/competitors")
        discovery = await client.get("/discovery")
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
    assert "ИСТОЧНИКИ ПОИСКА" in competitors.text or "ПОРТФЕЛЬ" in competitors.text
    assert "Найти лидов" in competitors.text
    assert "lazuno.uz" in competitors.text
    assert discovery.status_code == 200
    assert "Rotan" in discovery.text
    assert roadmap.status_code == 200
    assert "Стадия 3 из 7" in roadmap.text
    assert promoted.status_code == 200
    assert promoted.json()["ok"] is True


async def test_f1_portfolio_activate_ab_without_invented_handles(session_factory):
    """F1: новые verified seeds в каталоге; активация A+B только в БД."""
    from app.data.competitor_catalog import MONITORED_COMPETITORS

    handles = {seed.handle for seed in MONITORED_COMPETITORS}
    assert "divanchi.uz" in handles
    assert "focus.mebel" in handles
    assert "mogno_mebel_uz" in handles
    # Не активируем по умолчанию — иначе silent spend.
    for seed in MONITORED_COMPETITORS:
        if seed.handle in {"divanchi.uz", "focus.mebel", "mogno_mebel_uz"}:
            assert seed.active_by_default is False
            assert seed.tier in {"A", "B"}

    service = MarketIntelligenceService(session_factory)
    await service.sync_catalog()
    result = await service.activate_portfolio(tiers=("A", "B"), catalog_managed_only=True)
    assert result["activated"] >= 3
    assert "divanchi.uz" in result["handles"] or result["already_active"] >= 1

    async with session_factory() as session:
        active = set(
            await session.scalars(
                select(Competitor.normalized_handle).where(Competitor.active.is_(True))
            )
        )
        paused_c = list(
            await session.scalars(
                select(Competitor.normalized_handle).where(
                    Competitor.tier == "C",
                    Competitor.active.is_(False),
                    Competitor.catalog_managed.is_(True),
                )
            )
        )
    assert "divanchi.uz" in active
    assert "focus.mebel" in active
    assert "mogno_mebel_uz" in active
    # C остаются на паузе при F1 A+B.
    assert paused_c


async def test_portfolio_activate_api(session_factory):
    service = MarketIntelligenceService(session_factory)
    await service.sync_catalog()
    settings = Settings(_env_file=None, web_enabled=True, instagram_provider="replay", web_manager_id=1001)
    app = build_web_app(
        settings,
        WebQueryService(session_factory, hot_threshold=70),
        LeadWorkflowService(session_factory, hot_threshold=70),
        MonitorController(FakeMonitor()),  # type: ignore[arg-type]
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        page = await client.get("/competitors")
        response = await client.post(
            "/api/competitors/portfolio/activate",
            json={"tiers": "A,B", "catalog_managed_only": True},
        )
    assert page.status_code == 200
    assert "Включить портфель A+B" in page.text
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["activated"] + body["already_active"] >= 1
    assert "Live credits не открываются" in body["message"]
