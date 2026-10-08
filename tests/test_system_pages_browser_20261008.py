"""Real JS/layout smoke across the application, with every request intercepted."""

import json
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from httpx import ASGITransport, AsyncClient
from playwright.async_api import async_playwright

from app.services.product_catalog_service import ProductCatalogService
from tests.test_qa_smoke_pages import _app
from tests.test_system_pass_20261008 import _seed_rows

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("width", [390, 1440])
async def test_every_work_page_loads_without_js_errors_or_body_overflow(file_session_factory, width):
    session_factory = file_session_factory
    await _seed_rows(session_factory, 55)
    await ProductCatalogService(session_factory).sync_confirmed_catalog()
    app = _app(session_factory)
    paths = [
        "/", "/rattan", "/radar", "/radar?kind=hot&page=2", "/hot",
        "/leads", "/leads?view=list", "/leads?quality=garbage",
        "/contacts", "/contacts?page=2", "/tasks", "/deals",
        "/analytics", "/economics", "/catalog", "/audiences",
        "/audiences/quality", "/competitors", "/discovery", "/openings",
        "/roadmap", "/system", "/agent", "/leads/1", "/contacts/1", "/competitors/1",
    ]
    errors = []
    writes = []
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
                    return
                if request.method == "POST" and parsed.path == "/api/agent/sessions":
                    # The chat starts a local empty session on opening. Exercise
                    # this harmless initialization on the disposable DB only.
                    response = await client.post(parsed.path, content=request.post_data or "{}", headers={"Content-Type": "application/json"})
                    await route.fulfill(status=response.status_code, body=response.content, content_type="application/json")
                    return
                if request.method != "GET":
                    writes.append(request.url)
                    await route.fulfill(status=409, body=json.dumps({"detail": "Writes disabled in browser audit"}), content_type="application/json")
                    return
                if parsed.path.startswith("/static/"):
                    asset = ROOT / "app/web/static" / parsed.path.removeprefix("/static/")
                    content_type = {".js": "application/javascript", ".css": "text/css", ".html": "text/html", ".json": "application/json", ".svg": "image/svg+xml"}.get(asset.suffix, "application/octet-stream")
                    await route.fulfill(body=asset.read_bytes(), content_type=content_type)
                    return
                response = await client.get(parsed.path + ("?" + parsed.query if parsed.query else ""))
                await route.fulfill(status=response.status_code, body=response.content, content_type=response.headers.get("content-type", "text/html"))

            await page.route("**/*", serve)
            await page.add_init_script("window.setInterval = () => 0;")
            failures = []
            for path in paths:
                response = await page.goto("http://127.0.0.1" + path, wait_until="networkidle")
                if response.status != 200:
                    failures.append({"path": path, "status": response.status})
                    continue
                assert await page.locator("#main-content h1").is_visible(), path
                dimensions = await page.evaluate("""() => ({width: innerWidth, scroll: document.documentElement.scrollWidth,
                  wide: [...document.querySelectorAll('*')].filter(e => e.getBoundingClientRect().right > innerWidth + 1 && e.getBoundingClientRect().width > 0).sort((a,b) => b.getBoundingClientRect().right-a.getBoundingClientRect().right).slice(0,8).map(e => ({tag:e.tagName, cls:e.className, right:e.getBoundingClientRect().right, width:e.getBoundingClientRect().width, scroll:e.scrollWidth}))})""")
                if dimensions["scroll"] > width:
                    failures.append({"path": path, **dimensions})
            await browser.close()
    assert not failures, failures
    assert not errors, errors
    assert not writes, writes
