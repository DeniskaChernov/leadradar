"""No network: real adapter, budget ledger, durable checkpoints and request retries."""

import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import func, select

from app.config import Settings
from app.db.models import (
    Comment,
    Competitor,
    ContactEvent,
    CostEvent,
    CoverageStatus,
    ExternalBudgetReservation,
    Lead,
    Post,
    ReplyScanRequest,
    ReplyThreadState,
    ReservationStatus,
)
from app.providers.base import ProviderPrivacyError, ProviderResponseError
from app.providers.budgeted import BudgetedInstagramProvider, ScanBudget
from app.providers.fallback import FallbackInstagramProvider
from app.providers.mock import MockInstagramProvider
from app.providers.scrapecreators import ScrapeCreatorsProvider
from app.schemas.instagram import InstagramComment, InstagramPost
from app.services.contact_service import ContactService
from app.services.instagram_monitor import InstagramMonitor
from app.services.lead_service import LeadService
from app.services.lead_workflow_service import LeadWorkflowService
from app.services.monitor_controller import MonitorController
from app.services.operational_control_service import OperationalControlService
from app.services.reply_scan_service import ReplyScanConflict
from app.services.usage_service import ExternalUsageService
from app.web.app import build_web_app
from app.web.auth import WebRole, required_role
from app.web.queries import WebQueryService
from tests.conftest import seed_scrapecreators_instagram_policy
from tests.test_lead_service import StaticAnalyzer
from tests.test_monitor import RecordingNotifier


def _payload(id="reply", parent="root"):
    return {"id": id, "text": "Нужны 2 пластиковых стула, цена?",
            "created_at": datetime.now(UTC).isoformat(), "parent_comment_id": parent,
            "user": {"id": f"u-{id}", "username": f"user_{id}"}}


async def _setup(factory, handler, *, cap=2):
    await seed_scrapecreators_instagram_policy(factory)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = BudgetedInstagramProvider(
        ScrapeCreatorsProvider("fake", client=client), ExternalUsageService(factory),
        enabled=True, daily_limit=100, scan_budget=ScanBudget(default_limit=cap),
    )
    post = InstagramPost(platform_post_id="public-post", competitor="aiko.uz",
                         url="https://www.instagram.com/p/C5Rdyjq7YNa/",
                         caption="Пластиковые стулья", comments_count=8)
    contacts = ContactService(factory)
    root = await contacts.persist_signal(post, InstagramComment(
        platform_comment_id="root", username="buyer", profile_url="https://instagram.com/buyer/",
        text="Цена?", created_at=datetime.now(UTC),
    ))
    async with factory() as session:
        saved = await session.get(Post, root.post_id)
        saved.coverage_status = CoverageStatus.PARTIAL
        saved.comment_backfill_cursor = "parent-page-2"
        saved.last_comment_provider = "scrapecreators"
        await session.commit()
    monitor = InstagramMonitor(
        session_factory=factory, provider=provider, contact_service=contacts,
        lead_service=LeadService(factory, StaticAnalyzer(), 70),
        notifier=RecordingNotifier(), competitors=["aiko.uz"], process_existing_comments=True,
    )
    return client, monitor, root


def _page(comments, cursor=None, more=False, charge=1):
    return httpx.Response(200, json={"comments": comments, "cursor": cursor,
                                    "has_more": more, "credits_charged": charge})


async def test_manual_reply_scan_commits_parent_context_cost_history_and_skips_cached_retry(session_factory):
    calls = []

    def handler(request):
        calls.append(dict(request.url.params))
        assert request.url.path == "/v1/instagram/post/comment/replies"
        return _page([_payload(), _payload()])

    client, monitor, root = await _setup(session_factory, handler)
    try:
        service = monitor.reply_scans
        first, created = await service.accept("request-key-001", root.comment_id, 1, 2)
        assert created
        async with session_factory() as session:
            post = await session.get(Post, root.post_id)
            before = {column.name: getattr(post, column.name) for column in Post.__table__.columns}
        stats = await monitor.run_reply_cycle(first.id)
        assert stats.comments_created == stats.leads_created == 1
        replay, created = await service.accept("request-key-001", root.comment_id, 1, 2)
        assert not created and replay.status == "DONE"
        await monitor.run_reply_cycle(replay.id)
        cached, _ = await service.accept("request-key-002", root.comment_id, 1, 2)
        assert (await monitor.run_reply_cycle(cached.id)).comment_requests == 0
        assert len(calls) == 1 and calls[0]["comment_id"] == "root"
        async with session_factory() as session:
            reply = await session.scalar(select(Comment).where(Comment.platform_comment_id == "reply"))
            assert reply.parent_comment_text == "Цена?" and reply.parent_platform_comment_id == "root"
            assert await session.scalar(select(func.count(ContactEvent.id))) >= 2
            assert await session.scalar(select(func.sum(CostEvent.units))) == 1
            post = await session.get(Post, root.post_id)
            assert {column.name: getattr(post, column.name) for column in Post.__table__.columns} == before
            assert post.coverage_status == CoverageStatus.PARTIAL
            assert post.comment_backfill_cursor == "parent-page-2"
        preview = await service.preview(root.comment_id)
        assert preview["coverage"] == "FULL" and preview["saved_replies"] == 1
    finally:
        await client.aclose()


async def test_reply_page_limit_resumes_durable_cursor_and_has_no_duplicate_signals(session_factory):
    calls = []

    def handler(request):
        cursor = request.url.params.get("cursor")
        calls.append(cursor)
        return _page([_payload("two" if cursor else "one")], None if cursor else "page-2", not cursor)

    client, monitor, root = await _setup(session_factory, handler, cap=1)
    try:
        first, _ = await monitor.reply_scans.accept("request-key-001", root.comment_id, 1, 1)
        await monitor.run_reply_cycle(first.id)
        assert (await monitor.reply_scans.preview(root.comment_id))["has_continuation"]
        second, _ = await monitor.reply_scans.accept("request-key-002", root.comment_id, 1, 1)
        monitor.provider.set_scan_budget_limit(1)
        await monitor.run_reply_cycle(second.id)
        assert calls == [None, "page-2"]
        async with session_factory() as session:
            assert await session.scalar(select(func.count(Comment.id))) == 3
            assert await session.scalar(select(func.count(Lead.id))) == 2
    finally:
        await client.aclose()


async def test_paid_reply_failure_keeps_prior_page_and_blocks_retry_until_reconciled(session_factory):
    def handler(request):
        if request.url.params.get("cursor"):
            return httpx.Response(500, json={"error": "offline failure"})
        return _page([_payload("one")], "page-2", True)

    client, monitor, root = await _setup(session_factory, handler)
    try:
        first, _ = await monitor.reply_scans.accept("request-key-001", root.comment_id, 1, 2)
        assert (await monitor.run_reply_cycle(first.id)).errors == 1
        preview = await monitor.reply_scans.preview(root.comment_id)
        assert preview["saved_replies"] == 1 and preview["has_continuation"]
        async with session_factory() as session:
            assert await session.scalar(select(func.count(ExternalBudgetReservation.id)).where(
                ExternalBudgetReservation.status == ReservationStatus.UNCERTAIN,
            )) == 1
        second, _ = await monitor.reply_scans.accept("request-key-002", root.comment_id, 1, 2)
        assert (await monitor.run_reply_cycle(second.id)).comment_requests == 0
    finally:
        await client.aclose()


@pytest.mark.parametrize("kind", ["wrong_parent", "bad_record", "bad_cursor", "missing_cursor", "unknown_completion"])
async def test_reply_adapter_does_not_claim_full_from_bad_or_ambiguous_pages(kind):
    payload = {"comments": [_payload()], "cursor": None, "has_more": False}
    if kind == "wrong_parent":
        payload["comments"].append(_payload("wrong", "different-root"))
    elif kind == "bad_record":
        payload["comments"].append({"id": "broken"})
    elif kind == "bad_cursor":
        payload["cursor"] = {"invalid": True}
    elif kind == "missing_cursor":
        payload["has_more"] = True
    else:
        payload.pop("has_more")
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload))) as client:
        provider = ScrapeCreatorsProvider("fake", client=client)
        post = InstagramPost(platform_post_id="post", competitor="aiko.uz", url="https://instagram.com/p/public/")
        result = await provider.get_reply_batch(post, "root")
        assert not result.cursor_exhausted and result.coverage_status != "FULL"
        assert len(result.comments) == 1


async def test_reply_adapter_rejects_restricted_sources_and_drops_private_payload():
    post = InstagramPost(platform_post_id="post", competitor="aiko.uz", url="https://instagram.com/p/public/")
    item = _payload()
    item["user"].update(email="never-store@example.invalid", phone_number="do-not-store")
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: _page([item]))) as client:
        result = await ScrapeCreatorsProvider("fake", client=client).get_reply_batch(post, "root")
        assert "email" not in str(result.comments[0].raw_data) and "phone_number" not in str(result.comments[0].raw_data)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={
        "is_private": True, "comments": [item],
    }))) as client:
        with pytest.raises(ProviderPrivacyError):
            await ScrapeCreatorsProvider("fake", client=client).get_reply_batch(post, "root")


async def test_unsupported_replies_and_fallback_never_spend(session_factory):
    provider = BudgetedInstagramProvider(MockInstagramProvider(), ExternalUsageService(session_factory),
                                        enabled=True, daily_limit=100, scan_budget=ScanBudget(default_limit=1))
    fallback = FallbackInstagramProvider(provider, MockInstagramProvider())
    post = InstagramPost(platform_post_id="post", competitor="aiko.uz", url="https://instagram.com/p/public/")
    assert not fallback.supports_comment_replies
    with pytest.raises(ProviderResponseError):
        await fallback.get_reply_batch(post, "root")
    async with session_factory() as session:
        assert await session.scalar(select(func.count(CostEvent.id))) == 0


async def test_reply_cursor_cycle_across_separate_requests_is_visible_and_resumable(session_factory):
    def handler(request):
        cursor = request.url.params.get("cursor")
        return _page([_payload(cursor or "head")], "a" if cursor in {None, "b"} else "b", True)

    client, monitor, root = await _setup(session_factory, handler, cap=1)
    try:
        for index in range(3):
            monitor.provider.set_scan_budget_limit(1)
            request, _ = await monitor.reply_scans.accept(f"request-key-{index}", root.comment_id, 1, 1)
            stats = await monitor.run_reply_cycle(request.id)
        assert stats.errors == 1
        async with session_factory() as session:
            state = await session.get(ReplyThreadState, root.comment_id)
            assert state.last_error == "RepeatedReplyCursor" and state.next_cursor == "b"
    finally:
        await client.aclose()


async def test_request_key_conflict_and_stale_completed_thread_refresh(session_factory):
    calls = []
    client, monitor, root = await _setup(session_factory, lambda r: (calls.append(r) or _page([])))
    try:
        first, _ = await monitor.reply_scans.accept("request-key-001", root.comment_id, 1, 2)
        await monitor.run_reply_cycle(first.id)
        with pytest.raises(ReplyScanConflict):
            await monitor.reply_scans.accept("request-key-001", root.comment_id, 1, 3)
        async with session_factory() as session:
            state = await session.get(ReplyThreadState, root.comment_id)
            state.checked_at = datetime.now(UTC) - timedelta(hours=2)
            await session.commit()
        monitor.provider.set_scan_budget_limit(2)
        second, _ = await monitor.reply_scans.accept("request-key-002", root.comment_id, 1, 2)
        await monitor.run_reply_cycle(second.id)
        assert len(calls) == 2
    finally:
        await client.aclose()


async def test_reply_http_replay_concurrency_and_readonly_preview(session_factory):
    calls = []
    client, monitor, root = await _setup(session_factory, lambda r: (calls.append(r) or _page([_payload()])))
    # ASGI configuration is replay, but uses the actual adapter and ledger with mocked transport.
    controller = MonitorController(monitor)
    app = build_web_app(Settings(_env_file=None, instagram_provider="replay", web_manager_id=1, lead_search_enabled=True),
                        WebQueryService(session_factory, 70), LeadWorkflowService(session_factory, 70), controller)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as web:
            assert (await web.get(f"/api/scan/replies/{root.comment_id}")).status_code == 200
            assert calls == []
            headers = {"Idempotency-Key": "request-key-001"}
            body = {"max_credits": 2}
            accepted = await web.post(f"/api/scan/replies/{root.comment_id}", headers=headers, json=body)
            assert accepted.status_code == 200
            await controller.wait_current()
            replay = await web.post(f"/api/scan/replies/{root.comment_id}", headers=headers, json=body)
            assert replay.json()["status"] == "DONE" and len(calls) == 1
            assert (await web.get("/api/scan/replies/requests/request-key-001")).json()["result"]["comments_created"] == 1
            assert (await web.post(f"/api/scan/replies/{root.comment_id}", headers=headers, json={"max_credits": 3})).status_code == 409
            for credits in [0, -1, 21, True, 1.5, "abc"]:
                assert (await web.post(f"/api/scan/replies/{root.comment_id}", headers={"Idempotency-Key": "new-request-key"}, json={"max_credits": credits})).status_code == 400
            radar = (await web.get("/radar")).text
            assert "data-reply-panel" in radar and "Ответ в ветке" in radar
        assert required_role("POST", "/api/scan/replies/1") == WebRole.ADMIN
    finally:
        await client.aclose()


async def test_same_durable_operation_is_claimed_once(session_factory):
    calls = []
    client, monitor, root = await _setup(session_factory, lambda r: (calls.append(r) or _page([])))
    try:
        request, _ = await monitor.reply_scans.accept("request-key-atomic", root.comment_id, 1, 2)
        await asyncio.gather(monitor.run_reply_cycle(request.id), monitor.run_reply_cycle(request.id))
        assert len(calls) == 1
    finally:
        await client.aclose()


async def test_paused_source_nested_reply_and_interrupted_request_never_dispatch(session_factory):
    calls = []
    client, monitor, root = await _setup(session_factory, lambda r: (calls.append(r) or _page([])))
    try:
        request, _ = await monitor.reply_scans.accept("request-key-001", root.comment_id, 1, 2)
        async with session_factory() as session:
            row = await session.get(ReplyScanRequest, request.id)
            row.status = "RUNNING"  # Simulated crash; HTTP retry cannot restart delivery.
            await session.commit()
        await monitor.run_reply_cycle(request.id)
        async with session_factory() as session:
            source = await session.get(Competitor, root.competitor_id)
            source.active = False
            await session.commit()
        with pytest.raises(ValueError, match="приостановлен"):
            await monitor.reply_scans.accept("request-key-002", root.comment_id, 1, 2)
        assert calls == []
    finally:
        await client.aclose()


@pytest.mark.parametrize("armed", [False, True])
async def test_http_reply_start_requires_live_confirmation_and_kill_switch(session_factory, armed):
    calls = []
    client, monitor, root = await _setup(session_factory, lambda r: (calls.append(r) or _page([])))
    controller = MonitorController(monitor)
    ops = OperationalControlService(session_factory)
    await ops.set_radar_live(armed, manager_id=1)
    app = build_web_app(Settings(_env_file=None, instagram_provider="scrapecreators",
                                instagram_live_calls_enabled=armed, external_kill_switch=not armed,
                                external_live_unlock="ALLOW_EXTERNAL_CALLS",
                                lead_search_enabled=True, web_manager_id=1),
                        WebQueryService(session_factory, 70), LeadWorkflowService(session_factory, 70),
                        controller, ops_control=ops)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as web:
            result = await web.post(f"/api/scan/replies/{root.comment_id}",
                                    headers={"Idempotency-Key": "request-key-001"},
                                    json={"max_credits": 1, "confirm_live": not armed})
            assert result.status_code == (428 if armed else 409)
            assert calls == []
            async with session_factory() as session:
                assert await session.scalar(select(func.count(ReplyScanRequest.id))) == 0
    finally:
        await client.aclose()
