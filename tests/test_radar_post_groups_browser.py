"""Keyboard, mobile layout and deep navigation, with all requests intercepted."""

import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from httpx import ASGITransport, AsyncClient
from playwright.async_api import async_playwright

from tests.test_qa_smoke_pages import _app
from tests.test_radar_post_groups import _seed

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("width", [390, 1440])
async def test_grouped_results_collapse_and_open_every_comment_on_mobile_and_desktop(file_session_factory, width):
    _, posts, _, _ = await _seed(file_session_factory, post_count=3, comments_per_post=55)
    app = _app(file_session_factory)
    errors, writes = [], []
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
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
                elif parsed.path == "/api/radar/feed":
                    response = await client.get(parsed.path)
                    payload = response.json()
                    # The initial live update can shrink the block above results.
                    # The post heading must remain visible after that update.
                    payload["changes"], payload["hot_leads"] = [], []
                    await route.fulfill(body=json.dumps(payload), content_type="application/json")
                else:
                    response = await client.get(parsed.path + ("?" + parsed.query if parsed.query else ""))
                    await route.fulfill(status=response.status_code, body=response.content, content_type=response.headers.get("content-type", "text/html"))

            await page.route("**/*", serve)
            await page.add_init_script("window.setInterval = () => 0;")
            await page.goto("http://127.0.0.1/radar", wait_until="networkidle")
            assert await page.locator('[data-radar-company]').count() == 2
            assert await page.locator('[data-radar-post]').count() == 3
            assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            group = page.locator(f'[data-radar-post="{posts[1].id}"]')
            summary = group.locator('summary').first
            await summary.focus()
            await summary.press("Enter")
            assert await group.get_attribute("open") is None
            assert not await group.locator('.radar-post-body').is_visible()
            await summary.press("Enter")
            assert await group.locator('.radar-post-body').is_visible()
            # A previous action's saved scroll must not override a deep link.
            await page.add_init_script("sessionStorage.setItem('lr:scroll-y', '4200');")
            await group.locator('.radar-post-more').click()
            await page.wait_for_load_state('networkidle')
            assert parse_qs(urlsplit(page.url).query)["post"] == [str(posts[1].id)]
            assert await page.locator('[data-radar-post]').count() == 1
            assert await page.locator('.find-lead-card').count() == 50
            assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            assert await page.evaluate("""() => document.querySelector('#radar-post-results').getBoundingClientRect().top
                >= document.querySelector('.main-sticky-head').getBoundingClientRect().bottom""")
            await page.locator('[data-list-pagination] a[rel="next"]').first.click()
            assert await page.locator('.find-lead-card').count() == 5
            card = page.locator('.find-lead-card').first
            assert 'lead_id=' in await card.get_by_role('link', name='Написать', exact=True).get_attribute('href')
            await page.get_by_role('link', name='← Ко всем публикациям', exact=True).click()
            assert await page.locator('[data-radar-post]').count() == 3
            assert not errors and not writes
            await browser.close()
