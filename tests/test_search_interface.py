"""Result controls reveal their scope and never silently drop another filter."""

from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit

from httpx import ASGITransport, AsyncClient

from app.db.models import Lead, LeadStatus, SearchResultOrigin
from app.services.search_results_service import SearchResultsService
from tests.test_qa_smoke_pages import _app
from tests.test_radar_post_groups import _seed
from tests.test_search_results import _owned, _run


class Controls(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.anchors = []
        self.options = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.anchors.append(dict(attrs))
        elif tag == "option":
            self.options.append(dict(attrs))


async def test_each_filter_can_be_removed_without_losing_remaining_scope(session_factory):
    _, posts, comments, _ = await _seed(session_factory)
    run = await _run(session_factory)
    await _owned(session_factory, run, comments)
    values = {"view": "comments", "vertical": "FURNITURE", "q": "Нархи", "kind": "hot",
              "competitor": "alpha", "post": str(posts[0].id)}
    async with AsyncClient(transport=ASGITransport(app=_app(session_factory)), base_url="http://test") as client:
        response = await client.get(f"/searches/{run.id}", params={**values, "page": 12})
        assert response.status_code == 200
        controls = Controls(response.text)
        chips = {a["data-search-filter"]: a for a in controls.anchors if "data-search-filter" in a}
        assert chips.keys() == {"q", "kind", "competitor", "post"}
        for removed, anchor in chips.items():
            target = urlsplit(anchor["href"])
            assert target.path == f"/searches/{run.id}"
            assert target.fragment == "search-filter-panel"
            assert parse_qs(target.query) == {k: [v] for k, v in values.items() if k != removed}
            assert (await client.get(anchor["href"])).status_code == 200


async def test_source_picker_includes_rejected_comments_and_recovered_leads_only_in_scope(session_factory):
    _, _, comments, leads = await _seed(session_factory)
    discovered, recovered, unrelated = [await _run(session_factory) for _ in range(3)]
    async with session_factory() as session:
        for lead in leads:
            (await session.get(Lead, lead.id)).status = LeadStatus.NOT_LEAD
        session.add(SearchResultOrigin(comment_id=comments[0].id, discovered_run_id=discovered.id))
        # A later run recovered a candidate for an older comment at beta.
        (await session.get(Lead, leads[2].id)).status = LeadStatus.NEW
        session.add(SearchResultOrigin(comment_id=comments[2].id,
                                      discovered_run_id=unrelated.id, lead_run_id=recovered.id))
        await session.commit()
    service = SearchResultsService(session_factory, 70)
    for run, expected in ((discovered, ["alpha"]), (recovered, ["beta"]), (unrelated, ["beta"])):
        sources = await service.sources(await service.load(run.id), vertical="FURNITURE")
        assert [source.normalized_handle for source in sources] == expected
    empty = await _run(session_factory)
    assert not await service.sources(await service.load(empty.id), vertical="FURNITURE")
    assert not await service.sources(await service.load(discovered.id), vertical="ARTIFICIAL_RATTAN")


async def test_company_picker_and_quick_metrics_do_not_hide_active_filters(session_factory):
    _, _, comments, _ = await _seed(session_factory)
    run = await _run(session_factory)
    await _owned(session_factory, run, comments)
    async with AsyncClient(transport=ASGITransport(app=_app(session_factory)), base_url="http://test") as client:
        response = await client.get(f"/searches/{run.id}?competitor=%20ALPHA%20&kind=%20HOT%20&q=%20Нархи%20")
        assert response.status_code == 200
        controls = Controls(response.text)
        assert any(o.get("value") == "alpha" and "selected" in o for o in controls.options)
        assert {o["value"] for o in controls.options if o.get("value") in {"alpha", "beta"}} == {"alpha", "beta"}
        assert 'data-search-filter="competitor"' in response.text
        metric_links = [a["href"] for a in controls.anchors if a.get("class") == "search-metric-hot"]
        assert len(metric_links) == 1
        assert parse_qs(urlsplit(metric_links[0]).query) == {
            "vertical": ["FURNITURE"], "view": ["leads"], "kind": ["hot"],
        }
        hot = await client.get(metric_links[0])
        assert hot.status_code == 200 and hot.text.count('data-search-customer="') == 1
        # An unknown source is shown, rather than displaying "All companies".
        missing = await client.get(f"/searches/{run.id}?competitor=missing")
        assert any(o.get("value") == "missing" and "selected" in o for o in Controls(missing.text).options)
        assert "Сбросить фильтры" in missing.text


async def test_unsupported_kind_and_post_do_not_pretend_to_filter_people(session_factory):
    _, posts, comments, _ = await _seed(session_factory)
    run = await _run(session_factory)
    await _owned(session_factory, run, comments)
    async with AsyncClient(transport=ASGITransport(app=_app(session_factory)), base_url="http://test") as client:
        response = await client.get(f"/searches/{run.id}?kind=unknown&post={posts[0].id}")
    assert response.status_code == 200
    assert 'data-search-filter="' not in response.text
    assert response.text.count('data-search-customer="') == 1
