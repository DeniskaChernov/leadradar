from __future__ import annotations

import httpx
from sqlalchemy import func, select

from app.db.models import Lead, Post
from app.providers.mock import MockInstagramProvider
from app.providers.scrapecreators import ScrapeCreatorsProvider
from app.services.contact_service import ContactService
from app.services.instagram_monitor import InstagramMonitor
from app.services.lead_service import LeadService
from tests.test_lead_service import StaticAnalyzer


async def test_scrapecreators_comment_pagination_uses_cursor():
    calls: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        cursor = request.url.params.get("cursor")
        calls.append(cursor)
        if cursor is None:
            return httpx.Response(
                200,
                json={
                    "comments": [
                        {
                            "id": "c1",
                            "text": "narxi?",
                            "created_at": "2026-08-26T10:00:00.000Z",
                            "user": {"id": "u1", "username": "aziz"},
                        }
                    ],
                    "cursor": "next-page",
                },
            )
        return httpx.Response(
            200,
            json={
                "comments": [
                    {
                        "id": "c2",
                        "text": "qancha?",
                        "created_at": "2026-08-26T10:01:00.000Z",
                        "user": {"id": "u2", "username": "dilshod"},
                    }
                ],
                "cursor": None,
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = ScrapeCreatorsProvider("test", client=client, max_comment_pages=5)
    post = MockInstagramProvider()._post.model_copy(update={"comments_count": 2})

    result = await provider.get_comment_batch(post)

    assert [item.platform_comment_id for item in result.comments] == ["c1", "c2"]
    assert result.pages_fetched == 2
    assert result.coverage_status == "FULL"
    assert calls == [None, "next-page"]
    await client.aclose()


async def test_historical_baseline_is_analyzed_without_new_notification(session_factory):
    provider = MockInstagramProvider()

    class NullNotifier:
        async def notify_hot_lead(self, lead_id: int) -> int:
            raise AssertionError("Historical backfill must not notify")

        async def flush_pending(self) -> int:
            return 0

    lead_service = LeadService(session_factory, StaticAnalyzer(), hot_threshold=70)
    monitor = InstagramMonitor(
        session_factory=session_factory,
        provider=provider,
        contact_service=ContactService(session_factory),
        lead_service=lead_service,
        notifier=NullNotifier(),
        competitors=["aiko.uz"],
        process_existing_comments=False,
        analyze_baseline_comments=True,
        historical_analysis_batch_size=10,
    )

    first = await monitor.run_cycle()
    second = await monitor.run_cycle()

    assert first.comments_created == 1
    assert first.leads_created == 0
    assert second.historical_analyzed == 1
    async with session_factory() as session:
        assert await session.scalar(select(func.count(Lead.id))) == 1
        post = await session.scalar(select(Post).where(Post.platform_post_id == "mock-reel-001"))
        assert post is not None
        assert post.comments_fetched_count == 1
        assert post.last_synced_remote_count == 1
        assert post.coverage_status.value == "FULL"

async def test_web_dashboard_and_contacts_render(session_factory):
    from httpx import ASGITransport, AsyncClient

    from app.config import Settings
    from app.services.lead_workflow_service import LeadWorkflowService
    from app.services.monitor_controller import MonitorController
    from app.web.app import build_web_app
    from app.web.queries import WebQueryService

    settings = Settings(_env_file=None, telegram_bot_token="", web_enabled=True)
    controller = MonitorController(monitor=None)  # type: ignore[arg-type]
    app = build_web_app(
        settings,
        WebQueryService(session_factory, hot_threshold=70),
        LeadWorkflowService(session_factory, hot_threshold=70),
        controller,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        dashboard = await client.get("/")
        contacts = await client.get("/contacts")

    assert dashboard.status_code == 200
    assert "Что система нашла" in dashboard.text
    assert contacts.status_code == 200
    assert "Единая база людей" in contacts.text
