"""Search -> company -> publication navigation, with no providers or writes."""

from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from httpx import ASGITransport, AsyncClient
from playwright.async_api import async_playwright

from tests.test_qa_smoke_pages import _app
from tests.test_radar_post_groups import _seed
from tests.test_search_results import _owned, _run

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("width", [390, 1440])
async def test_results_navigation_and_deduplication_on_mobile_and_desktop(file_session_factory, width):
    _, _, comments, _ = await _seed(file_session_factory, comments_per_post=15)
    run = await _run(file_session_factory)
    await _owned(file_session_factory, run, comments)
    errors, writes = [], []
    async with AsyncClient(transport=ASGITransport(app=_app(file_session_factory)), base_url="http://test") as client:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            page = await browser.new_page(viewport={"width": width, "height": 900})
            page.on("pageerror", lambda error: errors.append(str(error)))

            async def serve(route):
                request = route.request
                parsed = urlsplit(request.url)
                if parsed.netloc != "127.0.0.1":
                    await route.fulfill(body="", content_type="application/javascript")
                elif request.method != "GET":
                    writes.append(request.url)
                    await route.fulfill(status=409, body='{"detail":"Writes disabled"}', content_type="application/json")
                elif parsed.path.startswith("/static/"):
                    asset = ROOT / "app/web/static" / parsed.path.removeprefix("/static/")
                    content_type = {".css": "text/css", ".js": "application/javascript", ".svg": "image/svg+xml"}.get(asset.suffix, "application/octet-stream")
                    await route.fulfill(body=asset.read_bytes(), content_type=content_type)
                else:
                    response = await client.get(parsed.path + ("?" + parsed.query if parsed.query else ""))
                    await route.fulfill(status=response.status_code, body=response.content,
                                        content_type=response.headers.get("content-type", "text/html"))

            await page.route("**/*", serve)
            await page.goto(f"http://127.0.0.1/searches/{run.id}")
            assert await page.locator('[data-search-customer]').count() == 1
            assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            await page.get_by_role("link", name="По компаниям", exact=True).click()
            assert await page.locator('.search-company-card').count() == 2
            await page.get_by_role("link", name="Посмотреть лидов и посты →").first.click()
            assert await page.locator('[data-radar-post]').count() == 2
            # One card per customer/post, all fifteen distinct comments remain reachable.
            assert await page.locator('.find-lead-card').count() == 2
            await page.get_by_role("link", name="Все новые комментарии поста →").first.click()
            assert urlsplit(page.url).path == f"/searches/{run.id}"
            assert parse_qs(urlsplit(page.url).query)["view"] == ["comments"]
            assert await page.locator('[data-radar-post]').count() == 1
            assert await page.locator('.find-lead-card').count() == 15
            assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            await page.get_by_role("link", name="Новые лиды", exact=True).click()
            assert await page.locator('[data-search-customer]').count() == 1
            await page.get_by_role("link", name="← История поисков", exact=True).click()
            assert await page.locator(f'[data-search-run="{run.id}"]').count() == 1
            assert not errors and not writes
            await browser.close()
