"""Real source boundaries, complete counts, and bounded access to large posts."""

from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event

from app.db.models import (
    Comment,
    Competitor,
    Contact,
    CoverageStatus,
    Lead,
    LeadStatus,
    Post,
    Vertical,
)
from app.services.radar_results_service import RadarPostGroup
from app.web.queries import WebQueryService
from tests.test_qa_smoke_pages import _app


async def _seed(factory, *, post_count=3, comments_per_post=1):
    now = datetime.now(UTC)
    async with factory() as session:
        sources = [Competitor(handle=name, normalized_handle=name, display_name=f"Company {name}") for name in ("alpha", "beta")]
        session.add_all(sources)
        await session.flush()
        posts = [Post(
            competitor_id=sources[0 if i < post_count - 1 else 1].id,
            platform_post_id=f"post-{i}", url=f"https://www.instagram.com/reel/post-{i}/",
            caption=f"Мебель публикация {i}", published_at=now,
            comments_count=comments_per_post, comments_fetched_count=comments_per_post,
            comments_checked_at=now, last_synced_remote_count=comments_per_post, coverage_status=CoverageStatus.FULL,
        ) for i in range(post_count)]
        session.add_all(posts)
        # One customer can comment on different posts; grouping must not merge them.
        contact = Contact(username="same_buyer", normalized_username="same_buyer", profile_url="https://instagram.com/same_buyer/")
        session.add(contact)
        await session.flush()
        comments = [Comment(
            platform_comment_id=f"comment-{post.id}-{i}", contact_id=contact.id,
            post_id=post.id, competitor_id=post.competitor_id, text=f"Нархи мебель {post.id}-{i}",
            created_at_platform=now, discovered_at=now,
        ) for post in posts for i in range(comments_per_post)]
        session.add_all(comments)
        await session.flush()
        leads = [Lead(
            contact_id=contact.id, comment_id=comment.id, competitor_id=comment.competitor_id,
            intent="ASK_PRICE", lead_score=85, status=LeadStatus.NEW,
        ) for comment in comments]
        session.add_all(leads)
        await session.commit()
    return sources, posts, comments, leads


def _post_groups(result):
    return [post for company in result.companies for post in company.posts]


async def test_results_keep_company_and_post_identity_even_for_same_customer(session_factory):
    sources, posts, comments, _ = await _seed(session_factory)
    result = await WebQueryService(session_factory, 70).radar_posts_page()
    assert (result.company_count, result.post_count, result.comment_count) == (2, 3, 3)
    assert [group.competitor.id for group in result.companies] == [source.id for source in sources]
    assert result.companies[0].post_count == 2
    assert result.companies[0].total == result.companies[0].hot == 2
    assert {group.post.id for group in _post_groups(result)} == {post.id for post in posts}
    assert {row[0].id for row in result.rows} == {comment.id for comment in comments}
    for company in result.companies:
        for group in company.posts:
            assert all(row[0].post_id == group.post.id and row[2].id == company.competitor.id for row in group.rows)


async def test_counts_and_previews_respect_statuses_and_prioritize_ready_leads(session_factory):
    _, posts, comments, leads = await _seed(session_factory, post_count=1, comments_per_post=5)
    async with session_factory() as session:
        saved = [await session.get(Lead, lead.id) for lead in leads]
        saved[0].status, saved[0].lead_score = LeadStatus.NEW, 60
        saved[1].status, saved[1].lead_score = LeadStatus.NOT_LEAD, 99
        saved[2].status, saved[2].lead_score = LeadStatus.AI_PENDING, 0
        await session.delete(saved[3])
        await session.commit()
    query = WebQueryService(session_factory, 70)
    preview = await query.radar_posts_page(preview_size=2)
    group = _post_groups(preview)[0]
    assert (group.total, group.leads, group.hot, group.pending, group.rejected) == (5, 2, 1, 2, 1)
    assert [row[0].id for row in group.rows] == [comments[4].id, comments[0].id]
    detail = await query.radar_posts_page(post_id=posts[0].id)
    assert len(detail.rows) == 5
    assert {row[0].id for row in detail.rows} == {comment.id for comment in comments}
    # HOT counters must not call a rejected high-scoring comment a HOT lead.
    assert _post_groups(detail)[0].hot == 1


@pytest.mark.parametrize(("filters", "expected"), [
    ({"competitor": "alpha"}, 2), ({"q": "публикация 0"}, 1),
    ({"q": "same_buyer"}, 3), ({"kind": "hot"}, 3),
    ({"kind": "pending"}, 0), ({"kind": "warm"}, 0),
    ({"vertical": "ARTIFICIAL_RATTAN"}, 0), ({"q": "missing"}, 0),
])
async def test_grouping_applies_existing_signal_filters_before_counting(session_factory, filters, expected):
    await _seed(session_factory)
    result = await WebQueryService(session_factory, 70).radar_posts_page(**filters)
    assert result.comment_count == result.post_count == expected
    assert len(result.rows) == expected


async def test_recency_baseline_and_vertical_rules_are_preserved(session_factory):
    sources, posts, comments, leads = await _seed(session_factory)
    async with session_factory() as session:
        (await session.get(Comment, comments[0].id)).created_at_platform = datetime.now(UTC) - timedelta(days=31)
        (await session.get(Comment, comments[1].id)).is_baseline = True
        (await session.get(Competitor, sources[1].id)).vertical = Vertical.ARTIFICIAL_RATTAN
        (await session.get(Lead, leads[2].id)).vertical = Vertical.ARTIFICIAL_RATTAN
        await session.commit()
    query = WebQueryService(session_factory, 70)
    assert (await query.radar_posts_page(vertical="FURNITURE")).comment_count == 1
    assert (await query.radar_posts_page(vertical="FURNITURE", kind="baseline")).comment_count == 1
    assert (await query.radar_posts_page(vertical="ARTIFICIAL_RATTAN")).comment_count == 1
    assert (await query.radar_posts_page(post_id=posts[2].id, vertical="FURNITURE")).post_count == 0


async def test_post_pagination_is_stable_and_company_totals_include_later_pages(session_factory):
    _, posts, _, _ = await _seed(session_factory, post_count=11)
    query = WebQueryService(session_factory, 70)
    first = await query.radar_posts_page()
    second = await query.radar_posts_page(page=2)
    assert first.pagination.total == 11 and first.pagination.pages == 2
    assert len(_post_groups(first)) == 8 and len(_post_groups(second)) == 3
    assert first.companies[0].post_count == first.companies[0].total == 10
    first_ids = {group.post.id for group in _post_groups(first)}
    second_ids = {group.post.id for group in _post_groups(second)}
    assert not first_ids & second_ids
    assert first_ids | second_ids == {post.id for post in posts}
    assert [group.post.id for group in _post_groups(first)] == [group.post.id for group in _post_groups(await query.radar_posts_page())]
    assert (await query.radar_posts_page(page=-1)).pagination.page == 1
    assert (await query.radar_posts_page(page=999)).pagination.page == 2


async def test_large_post_preview_is_bounded_but_all_comments_are_reachable(session_factory):
    _, posts, comments, _ = await _seed(session_factory, post_count=1, comments_per_post=113)
    query = WebQueryService(session_factory, 70)
    preview = await query.radar_posts_page()
    assert _post_groups(preview)[0].total == 113 and len(preview.rows) == 12
    pages = [await query.radar_posts_page(post_id=posts[0].id, page=number) for number in (1, 2, 3)]
    assert [len(page.rows) for page in pages] == [50, 50, 13]
    ids = [row[0].id for page in pages for row in page.rows]
    assert len(ids) == len(set(ids)) == 113
    assert set(ids) == {comment.id for comment in comments}


async def test_query_count_does_not_grow_per_post(session_factory):
    await _seed(session_factory, post_count=8, comments_per_post=15)
    statements = []
    engine = session_factory.kw["bind"].sync_engine

    def record(_connection, _cursor, statement, *_args):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        result = await WebQueryService(session_factory, 70).radar_posts_page()
    finally:
        event.remove(engine, "before_cursor_execute", record)
    assert len(result.rows) == 8 * 12
    assert len(statements) <= 5
    assert all(statement.lstrip().upper().startswith("SELECT") for statement in statements)


@pytest.mark.parametrize(("coverage", "checked", "cursor", "remote", "expected"), [
    (CoverageStatus.FULL, True, None, 5, "FULL"),
    (CoverageStatus.FULL, False, None, 5, "UNKNOWN"),
    (CoverageStatus.FULL, True, "next-page", 5, "PARTIAL"),
    (CoverageStatus.FULL, True, None, 6, "PARTIAL"),
    (CoverageStatus.PARTIAL, True, None, 5, "PARTIAL"),
    (CoverageStatus.LATEST_ONLY, True, None, 5, "LATEST_ONLY"),
])
def test_coverage_uses_saved_fetch_evidence(coverage, checked, cursor, remote, expected):
    post = Post(coverage_status=coverage, comments_count=5, last_synced_remote_count=remote,
                comments_checked_at=datetime.now(UTC) if checked else None, comment_backfill_cursor=cursor)
    assert RadarPostGroup(post, 0, 0, 0, 0, 0).coverage == expected


@pytest.mark.parametrize(("url", "allowed"), [
    ("https://www.instagram.com/reel/public/", True),
    ("https://instagram.com/p/public/", True),
    ("javascript:alert(1)", False), ("https://instagram.com.evil.example/p/", False),
    ("https://user:password@instagram.com/p/", False), ("https://[", False),
])
def test_public_post_links_only_allow_instagram_urls(url, allowed):
    group = RadarPostGroup(Post(url=url), 0, 0, 0, 0, 0)
    assert bool(group.public_url) is allowed


class _Links(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.links = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a":
            self.links.append(attrs)


async def test_web_deep_links_keep_filters_and_comment_pagination(session_factory):
    _, posts, _, _ = await _seed(session_factory, post_count=2, comments_per_post=55)
    app = _app(session_factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/radar?competitor=alpha&q=мебель&kind=hot")
        assert response.status_code == 200
        assert 'data-radar-company=' in response.text and 'data-radar-post=' in response.text
        links = _Links(response.text).links
        post_links = [link["href"] for link in links if "post=" in link.get("href", "")]
        assert post_links
        params = parse_qs(urlsplit(post_links[0]).query)
        assert params == {"vertical": ["FURNITURE"], "q": ["мебель"], "competitor": ["alpha"], "kind": ["hot"], "post": [str(posts[0].id)]}
        detail = await client.get(post_links[0])
        assert detail.status_code == 200 and "Показаны комментарии" in detail.text
        next_links = [link["href"] for link in _Links(detail.text).links if link.get("rel") == "next"]
        assert next_links
        params = parse_qs(urlsplit(next_links[0]).query)
        assert params["post"] == [str(posts[0].id)] and params["page"] == ["2"]
        assert params["q"] == ["мебель"] and params["competitor"] == ["alpha"] and params["kind"] == ["hot"]
        final_page = await client.get(next_links[0])
        assert final_page.status_code == 200
        assert final_page.text.count('class="find-lead-card"') == 5
        assert '/hot?vertical=FURNITURE&amp;lead_id=' in final_page.text or '/hot?vertical=FURNITURE&lead_id=' in final_page.text


async def test_render_escapes_post_content_and_rejected_comments_are_not_lead_cards(session_factory):
    _, posts, _, leads = await _seed(session_factory, post_count=1, comments_per_post=2)
    async with session_factory() as session:
        post = await session.get(Post, posts[0].id)
        post.caption, post.url = '<script>alert("post")</script>', 'javascript:alert(1)'
        (await session.get(Lead, leads[0].id)).status = LeadStatus.NOT_LEAD
        await session.commit()
    async with AsyncClient(transport=ASGITransport(app=_app(session_factory)), base_url="http://test") as client:
        response = await client.get('/radar')
        missing = await client.get('/radar?post=9999')
    assert response.status_code == missing.status_code == 200
    assert '<script>alert("post")</script>' not in response.text
    assert '&lt;script&gt;' in response.text and 'href="javascript:' not in response.text
    assert response.text.count('class="find-lead-card"') == 1
    assert 'Отсеян · не лид' in response.text
    assert 'Нет комментариев этой публикации' in missing.text
