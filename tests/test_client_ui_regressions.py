"""Real client templates and JavaScript with every browser request mocked."""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import pytest
import pytest_asyncio
from playwright.async_api import async_playwright
from sqlalchemy import select

from app.db.models import Deal, Lead, LeadStatus, Vertical
from tests.e2e.helpers import build_e2e_app
from tests.test_lead_workflow import create_lead

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (PROJECT_ROOT / "app/web/static/app.js").read_text(encoding="utf-8")
SCRIPT = SCRIPT.rsplit("})();", 1)[0] + "window.clientUiTest = {api};})();"


@pytest_asyncio.fixture
async def client_page(session_factory):
    lead_id = await create_lead(session_factory)
    async with session_factory() as session:
        contact_id = (await session.get(Lead, lead_id)).contact_id
    app = build_e2e_app(session_factory)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        html = (await client.get(f"/contacts/{contact_id}")).text
        catalog_html = (await client.get("/catalog")).text
    import_form = re.search(r'<form[^>]+action="/api/catalog/import".*?</form>', catalog_html, re.S)
    assert import_form is not None
    html = html.replace(
        "</main>", '<button type="button" data-lead-explain="1">Explain A</button>'
        '<button type="button" data-lead-explain="2">Explain B</button>'
        + import_form.group() + '<pre id="catalog-import-result" hidden></pre></main>',
    )
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        state = {"posts": [], "status": 200, "response": {"ok": True, "message": "Сохранено"}}
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))

        async def route_request(route):
            path = urlsplit(route.request.url).path
            if path == "/ui-client":
                await route.fulfill(body=html, content_type="text/html")
            elif path == "/static/app.js":
                await route.fulfill(body=SCRIPT, content_type="application/javascript")
            elif path == "/static/app.css":
                await route.fulfill(path=str(PROJECT_ROOT / "app/web/static/app.css"))
            elif route.request.method == "POST":
                state["posts"].append(
                    route.request.post_data_json
                    if route.request.headers.get("content-type", "").startswith("application/json")
                    else route.request.post_data
                )
                if state.get("release"):
                    await state["release"].wait()
                await route.fulfill(
                    status=state["status"], body=json.dumps(state["response"]), content_type="application/json",
                )
            elif path.endswith("/explain"):
                lead = path.split("/")[-2]
                await route.fulfill(body=json.dumps({
                    "username": f"client{lead}", "score": 91, "reason": f"Reason {lead}",
                    "contributions": [], "evidence": [], "evidence_ids": [],
                }), content_type="application/json")
            elif path.startswith("/api/"):
                await route.fulfill(body="{}", content_type="application/json")
            else:
                await route.fulfill(body="", content_type="application/javascript")

        await page.route("**/*", route_request)
        await page.add_init_script("""
          window.setInterval = () => 0;
          const originalTimeout = window.setTimeout;
          window.__reloads = 0;
          window.setTimeout = (fn, ms, ...args) => {
            if (String(fn).includes('location.reload')) { window.__reloads += 1; return 0; }
            return originalTimeout(fn, ms, ...args);
          };
        """)
        await page.goto("http://127.0.0.1/ui-client")
        await page.wait_for_function("Boolean(window.clientUiTest)")
        yield page, state, errors
        await browser.close()


async def test_closed_slow_explain_cannot_replace_next_client(client_page):
    page, _state, errors = client_page
    await page.evaluate("""() => {
      const realFetch = window.fetch;
      window.fetch = (url, options) => url === '/api/leads/1/explain'
        ? new Promise(resolve => { window.__releaseFirst = () => resolve(new Response(JSON.stringify({
            username: 'wrong-client', score: 91, reason: 'wrong-client', contributions: [], evidence: []
          }), {headers: {'Content-Type': 'application/json'}})); })
        : realFetch(url, options);
    }""")
    await page.locator('[data-lead-explain="1"]').click()
    await page.wait_for_function("Boolean(window.__releaseFirst)")
    await page.locator("[data-lead-explain-close]").click()
    await page.locator("#lead-explain").wait_for(state="hidden")
    await page.locator('[data-lead-explain="2"]').click()
    await page.wait_for_function("document.querySelector('[data-lead-explain-subtitle]').textContent.includes('client2')")
    await page.evaluate("window.__releaseFirst()")
    await page.wait_for_timeout(50)
    assert "Reason 2" in await page.locator("[data-lead-explain-body]").inner_text()
    assert await page.locator("[data-lead-explain-open]").get_attribute("href") == "/leads/2#ai-evidence"
    assert not errors


async def test_quick_explain_reopen_cancels_old_close_timer(client_page):
    page, _state, errors = client_page
    await page.locator('[data-lead-explain="1"]').click()
    await page.locator("[data-lead-explain-close]").click()
    await page.locator('[data-lead-explain="2"]').evaluate("element => element.click()")
    await page.wait_for_timeout(210)
    assert await page.locator("#lead-explain").evaluate("element => !element.hidden")
    assert await page.locator("[data-lead-explain-open]").get_attribute("href") == "/leads/2#ai-evidence"
    assert not errors


async def test_saved_note_stays_locked_until_reload_and_posts_once(client_page):
    page, state, errors = client_page
    form = page.locator('form[data-api-form][action$="/notes"]')
    await form.locator("textarea").fill("One manager note")
    await form.locator('button[type="submit"]').click()
    await page.wait_for_function("window.__reloads === 1")
    assert await form.locator('button[type="submit"]').is_disabled()
    assert await form.locator("textarea").is_disabled()
    # requestSubmit also exercises repeated Enter/programmatic dispatch while pending.
    await form.evaluate("element => element.requestSubmit()")
    await page.wait_for_timeout(50)
    assert state["posts"] == [{"text": "One manager note"}]
    assert not errors


async def test_pending_form_freezes_values_and_error_restores_original_controls(client_page):
    page, state, errors = client_page
    state.update(status=400, response={"detail": "Ошибка сохранения"}, release=asyncio.Event())
    form = page.locator('form[data-api-form][action$="/notes"]')
    await form.locator("textarea").fill("Keep this note")
    await form.evaluate("""element => {
      const field = document.createElement('input');
      field.name = 'protected'; field.value = 'old'; field.disabled = true; element.append(field);
    }""")
    await form.locator('button[type="submit"]').click()
    await page.wait_for_function("document.querySelector('form[action$=\"/notes\"] textarea').disabled")
    assert await form.locator("textarea").is_disabled()
    await form.evaluate("element => element.requestSubmit()")
    state["release"].set()
    await form.locator('button[type="submit"]').wait_for(state="visible")
    await page.wait_for_function("!document.querySelector('form[action$=\"/notes\"] textarea').disabled")
    assert await form.locator("textarea").input_value() == "Keep this note"
    assert await form.locator('input[name="protected"]').is_disabled()
    assert state["posts"] == [{"text": "Keep this note"}]
    assert await page.evaluate("window.__reloads") == 0
    assert not errors


async def test_form_lock_precedes_async_confirmation_and_cancel_restores(client_page):
    page, state, errors = client_page
    form = page.locator('form[data-api-form][action$="/notes"]')
    await form.locator("textarea").fill("Confirmed note")
    await form.locator('button[type="submit"]').evaluate("element => {element.dataset.confirm = 'Save this note?'}")
    await form.locator('button[type="submit"]').click()
    await page.locator("#confirm").wait_for(state="visible")
    assert await form.locator('button[type="submit"]').is_disabled()
    assert await form.locator("textarea").is_disabled()
    await form.evaluate("element => element.requestSubmit()")
    await page.locator("[data-confirm-cancel]").click()
    await page.wait_for_function("!document.querySelector('form[action$=\"/notes\"] textarea').disabled")
    assert not state["posts"]
    await form.locator('button[type="submit"]').click()
    await page.locator("[data-confirm-ok]").click()
    await page.wait_for_function("window.__reloads === 1")
    assert state["posts"] == [{"text": "Confirmed note"}]
    assert not errors


async def test_multipart_import_captures_file_and_submitter_before_lock(client_page):
    page, state, errors = client_page
    state["release"] = asyncio.Event()
    form = page.locator('form[action="/api/catalog/import"]')
    await form.locator('input[type="file"]').set_input_files({
        "name": "catalog.csv", "mimeType": "text/csv", "buffer": b"canonical_key,name\none,Sample",
    })
    await form.locator('button[value="false"]').click()
    assert await form.locator('button[value="true"]').is_disabled()
    assert await form.locator('input[type="file"]').is_disabled()
    await form.evaluate("element => element.requestSubmit(element.querySelector('button[value=\"true\"]'))")
    state["release"].set()
    await page.wait_for_function("!document.querySelector('form[action=\"/api/catalog/import\"] input').disabled")
    assert len(state["posts"]) == 1
    body = state["posts"][0]
    assert 'filename="catalog.csv"' in body
    assert "one,Sample" in body
    assert 'name="apply"\r\n\r\nfalse' in body
    assert await page.locator("#confirm").is_hidden()
    assert not errors


@pytest.mark.parametrize("body,content_type", [
    ("<html>Cloudflare challenge</html>", "text/html"),
    ("null", "application/json"), ("[]", "application/json"),
    ('"text"', "application/json"),
    ('{"ok":false,"message":"Not saved"}', "application/json"),
])
async def test_api_rejects_unconfirmed_success_responses(client_page, body, content_type):
    page, _state, errors = client_page
    message = await page.evaluate("""async ([body, contentType]) => {
      window.fetch = async () => new Response(body, {headers: {'Content-Type': contentType}});
      try { await clientUiTest.api('/api/contacts/1/notes', {method: 'POST', body: '{}'}); }
      catch (error) { return error.message; }
    }""", [body, content_type])
    assert message
    assert "<html>" not in message
    assert not errors


async def test_logout_retains_intentional_redirect_contract(client_page):
    page, _state, errors = client_page
    data = await page.evaluate("""async () => {
      window.fetch = async () => new Response('<html>Login</html>', {headers: {'Content-Type': 'text/html'}});
      return clientUiTest.api('/logout', {method: 'POST', body: '{}', expectJson: false});
    }""")
    assert data["ok"] is True
    assert not errors


@pytest.mark.parametrize("vertical", [Vertical.FURNITURE, Vertical.ARTIFICIAL_RATTAN])
async def test_write_links_keep_lead_vertical_and_open_the_same_client(session_factory, vertical):
    lead_id = await create_lead(session_factory)
    async with session_factory() as session:
        lead = await session.get(Lead, lead_id)
        lead.vertical = vertical
        contact_id = lead.contact_id
        await session.commit()
    app = build_e2e_app(session_factory)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        expected = f"/hot?vertical={vertical.value}&lead_id={lead_id}"
        for path in (f"/leads/{lead_id}", f"/contacts/{contact_id}"):
            html = (await client.get(path)).text
            assert f'href="{expected}"' in html
        hot = await client.get(expected)
        assert hot.status_code == 200
        assert f'data-lead-id="{lead_id}"' in hot.text
        assert f'data-hot-vertical="{vertical.value}"' in hot.text
    async with session_factory() as session:
        assert len((await session.scalars(select(Lead))).all()) == 1


@pytest.mark.parametrize("status", [LeadStatus.NOT_LEAD, LeadStatus.WON, LeadStatus.LOST])
@pytest.mark.parametrize("with_deal", [False, True])
async def test_closed_client_has_no_deal_mutation_forms(session_factory, status, with_deal):
    lead_id = await create_lead(session_factory)
    async with session_factory() as session:
        lead = await session.get(Lead, lead_id)
        lead.status = status
        if with_deal:
            session.add(Deal(lead_id=lead_id, contact_id=lead.contact_id, product_name="Stored deal"))
        await session.commit()
    app = build_e2e_app(session_factory)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get(f"/leads/{lead_id}")
    assert response.status_code == 200
    assert f'action="/api/leads/{lead_id}/deal"' not in response.text
    assert 'action="/api/deals/' not in response.text
    assert "Лид закрыт:" in response.text
    if with_deal:
        assert "Stored deal" in response.text
