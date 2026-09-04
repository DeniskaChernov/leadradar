from __future__ import annotations

from datetime import UTC, datetime

from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.providers.mock import MockInstagramProvider
from app.schemas.instagram import InstagramComment
from app.services.contact_service import ContactService
from app.services.instagram_monitor import InstagramMonitor
from app.services.lead_service import LeadService
from app.services.lead_workflow_service import LeadWorkflowService
from app.services.monitor_controller import MonitorController
from app.services.usage_service import ExternalUsageService
from app.web.app import build_web_app
from app.web.queries import WebQueryService
from tests.test_lead_service import StaticAnalyzer


class _NullNotifier:
    async def notify_hot_lead(self, _lead_id: int) -> int:
        return 0

    async def flush_pending(self) -> int:
        return 0


class _FakeMonitor:
    provider = None


async def test_monitor_auto_backfills_fresh_comments(session_factory):
    provider = MockInstagramProvider()
    await ContactService(session_factory).persist_signal(
        provider._post,
        InstagramComment(
            platform_comment_id="fresh-backfill-1",
            platform_user_id="fresh-user-1",
            username="fresh_user",
            display_name="Fresh",
            profile_url="https://www.instagram.com/fresh_user/",
            text="narxi qancha?",
            created_at=datetime.now(UTC),
        ),
        is_baseline=True,
    )
    monitor = InstagramMonitor(
        session_factory=session_factory,
        provider=provider,
        contact_service=ContactService(session_factory),
        lead_service=LeadService(
            session_factory,
            StaticAnalyzer(),
            hot_threshold=70,
            signal_max_age_days=30,
        ),
        notifier=_NullNotifier(),
        competitors=["aiko.uz"],
        process_existing_comments=False,
        auto_analyze_fresh_batch_size=5,
        analyze_baseline_comments=False,
        max_signal_age_days=30,
    )

    stats = await monitor.run_cycle(force=True)

    assert stats.fresh_backfilled >= 1


async def test_review_all_endpoint_scores_fresh_comments(session_factory):
    provider = MockInstagramProvider()
    await ContactService(session_factory).persist_signal(
        provider._post,
        InstagramComment(
            platform_comment_id="review-all-1",
            platform_user_id="review-user-1",
            username="review_user",
            display_name="Review",
            profile_url="https://www.instagram.com/review_user/",
            text="+",
            created_at=datetime.now(UTC),
        ),
        is_baseline=True,
    )
    settings = Settings(
        _env_file=None,
        web_enabled=True,
        web_manager_id=1001,
        instagram_signal_max_age_days=30,
    )
    app = build_web_app(
        settings,
        WebQueryService(session_factory, hot_threshold=70, signal_max_age_days=30),
        LeadWorkflowService(session_factory, hot_threshold=70),
        MonitorController(_FakeMonitor()),  # type: ignore[arg-type]
        ExternalUsageService(session_factory),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/signals/review-all",
            json={"limit": 10, "gpt_limit": 5},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["processed"] >= 1
    assert "Оценено комментариев" in payload["message"]


async def test_signal_overview_counts_actionable_without_lead(session_factory):
    provider = MockInstagramProvider()
    await ContactService(session_factory).persist_signal(
        provider._post,
        InstagramComment(
            platform_comment_id="overview-fresh-1",
            platform_user_id="overview-user-1",
            username="overview_user",
            display_name="Overview",
            profile_url="https://www.instagram.com/overview_user/",
            text="qancha?",
            created_at=datetime.now(UTC),
        ),
        is_baseline=True,
    )
    stale_at = datetime(2020, 1, 1, tzinfo=UTC)
    await ContactService(session_factory).persist_signal(
        provider._post,
        InstagramComment(
            platform_comment_id="overview-stale-1",
            platform_user_id="overview-user-2",
            username="stale_user",
            display_name="Stale",
            profile_url="https://www.instagram.com/stale_user/",
            text="eski",
            created_at=stale_at,
        ),
        is_baseline=True,
    )

    overview = await WebQueryService(session_factory, hot_threshold=70).signal_overview()

    assert overview["unprocessed"] >= 2
    assert overview["unprocessed_actionable"] >= 1
    assert overview["unprocessed"] > overview["unprocessed_actionable"]
