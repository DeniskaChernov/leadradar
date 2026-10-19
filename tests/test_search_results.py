"""A saved search owns new results; repeat ingestion and people do not duplicate cards."""

from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.db.models import (
    Comment,
    Contact,
    ContactEvent,
    Lead,
    LeadStatus,
    MonitorRun,
    MonitorRunStatus,
    SearchResultOrigin,
)
from app.schemas.instagram import InstagramComment, InstagramPost
from app.services.ai_service import RuleBasedLeadAnalyzer
from app.services.contact_service import ContactService
from app.services.instagram_monitor import CycleStats
from app.services.lead_service import LeadService
from app.services.monitor_controller import MonitorController
from app.services.monitor_run_service import MonitorRunService
from app.services.search_results_service import SearchResultsService
from app.web.queries import WebQueryService
from tests.test_qa_smoke_pages import _app
from tests.test_radar_post_groups import _seed


async def _run(factory, *, exact=True, **kwargs):
    async with factory() as session:
        run = MonitorRun(result_tracking_version=1 if exact else None,
                         status=kwargs.pop("status", MonitorRunStatus.SUCCESS), **kwargs)
        session.add(run)
        await session.commit()
        return run


async def _owned(factory, run, comments):
    async with factory() as session:
        session.add_all([SearchResultOrigin(comment_id=c.id, discovered_run_id=run.id,
                                            lead_run_id=run.id) for c in comments])
        await session.commit()


async def test_creation_provenance_is_atomic_immutable_and_idempotent(session_factory):
    first = await _run(session_factory)
    second = await _run(session_factory)
    contacts = ContactService(session_factory)
    leads = LeadService(session_factory, RuleBasedLeadAnalyzer(), 70)
    post = InstagramPost(platform_post_id="origin-post", competitor="origin",
                         url="https://instagram.com/p/origin-post/", caption="Обеденные стулья")
    comment = InstagramComment(platform_comment_id="origin-comment", username="customer",
                               text="Сколько стоит стул?", profile_url="https://instagram.com/customer/",
                               created_at=datetime.now(UTC))
    signal = await contacts.persist_signal(post, comment, monitor_run_id=first.id)
    async with session_factory() as session:
        origin = await session.get(SearchResultOrigin, signal.comment_id)
        assert origin.discovered_run_id == first.id and origin.lead_run_id is None
        assert await session.scalar(select(func.count(Lead.id))) == 0
    # A crash after the comment commit does not lose provenance. A later run
    # can create the missing lead without pretending it discovered the comment.
    duplicate = await contacts.persist_signal(post, comment, monitor_run_id=second.id)
    lead = await leads.ensure_analyzing(duplicate, monitor_run_id=second.id)
    assert not duplicate.created and lead.created
    repeated = await leads.ensure_analyzing(duplicate, monitor_run_id=first.id)
    assert not repeated.created
    async with session_factory() as session:
        origin = await session.get(SearchResultOrigin, signal.comment_id)
        assert (origin.discovered_run_id, origin.lead_run_id) == (first.id, second.id)
        assert await session.scalar(select(func.count(Comment.id))) == 1
        assert await session.scalar(select(func.count(Lead.id))) == 1
        # COMMENT_FOUND plus LEAD_CREATED; neither is repeated by retries.
        assert await session.scalar(select(func.count(ContactEvent.id))) == 2


async def test_exact_runs_never_infer_results_from_overlapping_timestamps(session_factory):
    _, _, comments, _ = await _seed(session_factory)
    now = datetime.now(UTC)
    first = await _run(session_factory, started_at=now, completed_at=now)
    second = await _run(session_factory, started_at=now, completed_at=now)
    empty = await _run(session_factory, started_at=now, completed_at=now)
    await _owned(session_factory, first, comments[:2])
    await _owned(session_factory, second, comments[2:])
    service = SearchResultsService(session_factory, 70)
    query = WebQueryService(session_factory, 70)
    for run, expected in ((first, 2), (second, 1), (empty, 0)):
        scope = await service.load(run.id)
        result = await query.signals_page(comment_ids=scope.comment_ids(comments=True))
        assert result.total == expected
    assert (await service.summary(await service.load(first.id), vertical="FURNITURE"))["people"] == 1


async def test_unique_people_keep_all_posts_and_filters_select_matching_evidence(session_factory):
    _, posts, comments, _ = await _seed(session_factory)
    run = await _run(session_factory)
    await _owned(session_factory, run, comments)
    service = SearchResultsService(session_factory, 70)
    scope = await service.load(run.id)
    query = WebQueryService(session_factory, 70)
    filters = dict(comment_ids=scope.comment_ids(comments=False), unique_contacts=True)
    result = await query.signals_page(**filters)
    assert result.total == 1
    again = await query.signals_page(**filters)
    assert result.rows[0][0].id == again.rows[0][0].id
    for company in ("alpha", "beta"):
        scoped = await query.signals_page(competitor=company, **filters)
        assert scoped.total == 1 and scoped.rows[0][2].normalized_handle == company
    assert (await query.signals_page(comment_ids=scope.comment_ids(comments=True))).total == 3
    per_post = await query.radar_posts_page(comment_ids=scope.comment_ids(comments=False), unique_per_post=True)
    assert per_post.post_count == 3 and per_post.comment_count == 3
    grouped = await query.radar_posts_page(post_id=posts[0].id, comment_ids=scope.comment_ids(comments=True))
    assert grouped.comment_count == 1
    summary = await service.summary(scope, vertical="FURNITURE")
    assert summary == {"comments": 3, "people": 1, "pending": 0, "hot": 1, "repeated_cards": 2}
    companies = await service.companies(scope, vertical="FURNITURE")
    assert len(companies) == 2
    assert sum(row.comments for row in companies) == 3
    async with session_factory() as session:
        assert await session.scalar(select(func.count(Comment.id))) == 3
        assert await session.scalar(select(func.count(Lead.id))) == 3


async def test_pending_and_rejected_are_not_reported_as_confirmed_hot(session_factory):
    _, _, comments, leads = await _seed(session_factory)
    run = await _run(session_factory)
    await _owned(session_factory, run, comments)
    async with session_factory() as session:
        for lead in leads:
            saved = await session.get(Lead, lead.id)
            saved.status = LeadStatus.NOT_LEAD if lead.id == leads[0].id else LeadStatus.AI_PENDING
        await session.commit()
    service = SearchResultsService(session_factory, 70)
    scope = await service.load(run.id)
    summary = await service.summary(scope, vertical="FURNITURE")
    assert summary["hot"] == 0 and summary["pending"] == summary["people"] == 1
    assert (await WebQueryService(session_factory, 70).signals_page(
        comment_ids=scope.comment_ids(comments=False), unique_contacts=True,
    )).total == 1
    assert (await WebQueryService(session_factory, 70).signals_page(
        comment_ids=scope.comment_ids(comments=False), unique_contacts=True, kind="hot",
    )).total == 0


async def test_legacy_search_window_excludes_next_scan_and_retains_old_results(session_factory):
    _, _, comments, leads = await _seed(session_factory)
    started = datetime.now(UTC) - timedelta(days=100)
    old = await _run(session_factory, exact=False, started_at=started, completed_at=started + timedelta(hours=3))
    await _run(session_factory, exact=False, started_at=started + timedelta(hours=1))
    async with session_factory() as session:
        for index, comment in enumerate(comments):
            (await session.get(Comment, comment.id)).discovered_at = started + timedelta(minutes=index * 60)
            (await session.get(Lead, leads[index].id)).created_at = started + timedelta(minutes=index * 60)
        await session.commit()
    service = SearchResultsService(session_factory, 70)
    scope = await service.load(old.id)
    assert not scope.exact
    result = await WebQueryService(session_factory, 70).signals_page(comment_ids=scope.comment_ids(comments=True))
    assert [row[0].id for row in result.rows] == [comments[0].id]


class Links(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.links = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.links.append(dict(attrs).get("href", ""))


@pytest.mark.parametrize("view", ["leads", "companies", "posts", "comments"])
async def test_result_views_and_source_links_remain_inside_selected_run(session_factory, view):
    _, _, comments, _ = await _seed(session_factory)
    run = await _run(session_factory, status=MonitorRunStatus.FAILED)
    await _owned(session_factory, run, comments)
    async with AsyncClient(transport=ASGITransport(app=_app(session_factory)), base_url="http://test") as client:
        response = await client.get(f"/searches/{run.id}?view={view}&vertical=FURNITURE")
    assert response.status_code == 200, response.text
    assert f"Поиск #{run.id}" in response.text
    assert "одна карточка на человека" in response.text
    assert "по времени создания" not in response.text
    links = Links(response.text).links
    detail_links = [url for url in links if url.startswith(f"/searches/{run.id}?")]
    assert detail_links
    assert all(parse_qs(urlsplit(url).query).get("vertical") == ["FURNITURE"] for url in detail_links)
    if view == "leads":
        assert response.text.count('data-search-customer="') == 1
    if view == "posts":
        post_links = [url for url in detail_links if "post" in parse_qs(urlsplit(url).query)]
        assert post_links and all("/radar" not in url for url in post_links)


async def test_empty_exact_run_failed_run_history_and_unknown_run(session_factory):
    await _seed(session_factory)
    empty = await _run(session_factory, status=MonitorRunStatus.FAILED)
    async with session_factory() as session:
        run = await session.get(MonitorRun, empty.id)
        run.status = MonitorRunStatus.FAILED
        run.error = "Source timeout"
        await session.commit()
    async with AsyncClient(transport=ASGITransport(app=_app(session_factory)), base_url="http://test") as client:
        detail = await client.get(f"/searches/{empty.id}")
        history = await client.get("/searches")
        invalid = await client.get("/searches/999999")
    assert detail.status_code == history.status_code == 200 and invalid.status_code == 404
    assert 'data-search-customer="' not in detail.text
    assert "Новых лидов по этим условиям нет" in detail.text
    assert "Source timeout" in detail.text and "Source timeout" in history.text
    assert f"/searches/{empty.id}?view=companies" in history.text


async def test_all_post_comments_link_clears_lead_filters_without_leaving_search(session_factory):
    _, _, comments, _ = await _seed(session_factory)
    run = await _run(session_factory)
    await _owned(session_factory, run, comments)
    async with AsyncClient(transport=ASGITransport(app=_app(session_factory)), base_url="http://test") as client:
        response = await client.get(f"/searches/{run.id}?view=posts&kind=hot&q=Нархи&competitor=alpha")
        links = [url for url in Links(response.text).links if "post" in parse_qs(urlsplit(url).query)]
        assert links
        for target in links:
            params = parse_qs(urlsplit(target).query)
            assert urlsplit(target).path == f"/searches/{run.id}"
            assert params["view"] == ["comments"]
            assert not {"kind", "q", "competitor"} & params.keys()


async def test_controller_persists_run_before_ingestion_and_exposes_result_identity(session_factory):
    seen = []

    class Monitor:
        async def run_cycle(self, *, monitor_run_id=None, force=True, vertical=None):
            async with session_factory() as session:
                run = await session.get(MonitorRun, monitor_run_id)
                assert run.result_tracking_version == 1 and run.vertical == "FURNITURE"
            seen.append(monitor_run_id)
            return CycleStats(comments_existing=4)

    controller = MonitorController(Monitor(), MonitorRunService(session_factory, "mock"))
    assert controller.start_cycle("web", vertical="FURNITURE")
    assert controller.snapshot().last_run_id is None
    await controller.wait_current()
    assert controller.snapshot().last_run_id == seen[0]
    async with session_factory() as session:
        assert (await session.get(MonitorRun, seen[0])).stats_json["comments_existing"] == 4
    assert controller.start_cycle("web", vertical="FURNITURE")
    assert controller.snapshot().last_run_id is None
    await controller.wait_current()
    assert seen[1] != seen[0]


async def test_real_monitor_commits_origins_before_notification_and_repeat_scan_is_empty(session_factory):
    from app.providers.mock import MockInstagramProvider
    from app.services.instagram_monitor import InstagramMonitor
    from tests.test_lead_service import StaticAnalyzer

    class Notifier:
        async def flush_pending(self):
            return 0

        async def notify_hot_lead(self, lead_id):
            async with session_factory() as session:
                lead = await session.get(Lead, lead_id)
                origin = await session.get(SearchResultOrigin, lead.comment_id)
                assert origin.lead_run_id is not None and origin.discovered_run_id is not None
            return 0

    provider = MockInstagramProvider()
    monitor = InstagramMonitor(session_factory=session_factory, provider=provider,
        contact_service=ContactService(session_factory), lead_service=LeadService(session_factory, StaticAnalyzer(), 70),
        notifier=Notifier(), competitors=["aiko.uz"], process_existing_comments=True,
        force_refresh_seconds=0)
    controller = MonitorController(monitor, MonitorRunService(session_factory, "mock"))
    controller.start_cycle("web", vertical="FURNITURE")
    first_stats = await controller.wait_current()
    first_run = controller.snapshot().last_run_id
    controller.start_cycle("web", vertical="FURNITURE")
    second_stats = await controller.wait_current()
    second_run = controller.snapshot().last_run_id
    assert first_stats.comments_created == first_stats.leads_created == 1
    assert second_stats.comments_created == second_stats.leads_created == 0
    service = SearchResultsService(session_factory, 70)
    assert (await service.summary(await service.load(first_run), vertical="FURNITURE"))["people"] == 1
    assert (await service.summary(await service.load(second_run), vertical="FURNITURE"))["people"] == 0


async def test_new_search_identity_is_returned_by_both_polling_endpoints(session_factory):
    from app.config import Settings
    from app.services.lead_workflow_service import LeadWorkflowService
    from app.web.app import build_web_app
    from tests.test_search_preparation import CountingMonitor

    controller = MonitorController(CountingMonitor(), MonitorRunService(session_factory, "mock"))
    controller.start_cycle("web", vertical="FURNITURE")
    await controller.wait_current()
    app = build_web_app(Settings(_env_file=None, web_enabled=True, web_manager_id=1001),
        WebQueryService(session_factory, 70), LeadWorkflowService(session_factory, 70), controller)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for endpoint in ("/api/scan/progress", "/api/radar/feed"):
            response = await client.get(endpoint)
            assert response.status_code == 200
            assert response.json()["last_run_id"] == controller.snapshot().last_run_id


async def test_unique_results_and_post_previews_do_not_drop_later_pages(session_factory):
    _, posts, comments, _ = await _seed(session_factory, post_count=1)
    run = await _run(session_factory)
    await _owned(session_factory, run, comments)
    async with session_factory() as session:
        for index in range(51):
            customer = Contact(username=f"buyer_{index}", normalized_username=f"buyer_{index}",
                               profile_url=f"https://instagram.com/buyer_{index}/")
            session.add(customer)
            await session.flush()
            comment = Comment(contact_id=customer.id, post_id=posts[0].id, competitor_id=posts[0].competitor_id,
                              platform_comment_id=f"paging-{index}", text="Цена стула?")
            session.add(comment)
            await session.flush()
            session.add_all([Lead(contact_id=customer.id, comment_id=comment.id,
                competitor_id=comment.competitor_id, status=LeadStatus.NEW, lead_score=80),
                SearchResultOrigin(comment_id=comment.id, discovered_run_id=run.id, lead_run_id=run.id)])
        await session.commit()
    scope = await SearchResultsService(session_factory, 70).load(run.id)
    query = WebQueryService(session_factory, 70)
    filters = dict(comment_ids=scope.comment_ids(comments=False), unique_contacts=True)
    first, second = await query.signals_page(**filters), await query.signals_page(page=2, **filters)
    assert first.total == second.total == 52
    ids = [{row[1].id for row in result.rows} for result in (first, second)]
    assert len(ids[0]) == 50 and len(ids[1]) == 2 and not ids[0] & ids[1]
    grouped = await query.radar_posts_page(comment_ids=scope.comment_ids(comments=True))
    assert grouped.comment_count == 52 and len(grouped.rows) == 12
    detail = await query.radar_posts_page(post_id=posts[0].id, page=2,
                                          comment_ids=scope.comment_ids(comments=True))
    assert detail.pagination.total == 52 and len(detail.rows) == 2


@pytest.mark.parametrize("query", ["НАРХИ", "нархи", "НаРхИ", "SAME_BUYER"])
async def test_result_text_filter_handles_unicode_case_without_moving_search_scope(session_factory, query):
    _, _, comments, _ = await _seed(session_factory)
    run = await _run(session_factory)
    await _owned(session_factory, run, comments[:2])
    scope = await SearchResultsService(session_factory, 70).load(run.id)
    # Repeated query services reuse the already-open pooled connection safely.
    for _ in range(2):
        result = await WebQueryService(session_factory, 70).signals_page(
            q=query, comment_ids=scope.comment_ids(comments=True),
        )
        assert result.total == 2
        assert {row[0].id for row in result.rows} == {c.id for c in comments[:2]}
