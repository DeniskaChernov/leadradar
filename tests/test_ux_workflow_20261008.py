"""Supported UX flows in Chromium; ASGI reads use an isolated database.

Every browser request is intercepted. Scan POSTs are simulated and cannot spend
credits, contact Instagram, generate AI text or alter the running cabinet.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import pytest_asyncio
from playwright.async_api import async_playwright

from app.config import Settings
from app.db.models import Lead, LeadStatus
from app.services.lead_workflow_service import LeadWorkflowService
from app.services.monitor_controller import MonitorController
from app.services.operational_control_service import OperationalControlService
from app.web.app import build_web_app
from app.web.queries import WebQueryService
from tests.conftest import seed_scrapecreators_instagram_policy
from tests.test_lead_workflow import create_lead

ROOT = Path(__file__).resolve().parents[1]


@pytest_asyncio.fixture
async def ux_page(session_factory):
    await seed_scrapecreators_instagram_policy(session_factory)
    ids = []
    for index in range(5):
        ids.append(await create_lead(session_factory, f"ux-{index}", f"buyer-{index}"))
    async with session_factory() as session:
        for lead_id, score, status in zip(ids, [92, 81, 62, 85, 94], [
            LeadStatus.NEW, LeadStatus.NEW, LeadStatus.NEW, LeadStatus.NOT_LEAD, LeadStatus.WON,
        ], strict=True):
            lead = await session.get(Lead, lead_id)
            lead.lead_score = score
            lead.status = status
        await session.commit()
    settings = Settings(
        _env_file=None, web_enabled=True, web_auth_enabled=False, web_manager_id=1001,
        lead_search_enabled=True,
        instagram_provider="scrapecreators", instagram_live_calls_enabled=True,
        external_live_unlock="ALLOW_EXTERNAL_CALLS", external_kill_switch=False,
        instagram_daily_request_limit=100, monitor_schedule_enabled=False,
        openai_live_calls_enabled=False,
    )
    ops = OperationalControlService(session_factory)
    await ops.load()
    await ops.set_radar_live(True, manager_id=1001)
    app = build_web_app(
        settings, WebQueryService(session_factory, hot_threshold=70),
        LeadWorkflowService(session_factory, hot_threshold=70),
        MonitorController(None), ops_control=ops,  # type: ignore[arg-type]
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        preview = (await client.get("/api/scan/preview?max_credits=5")).json()
        assert preview["can_start"], preview["blocking_reasons"]
        state = {"posts": [], "gets": [], "preview": preview, "ids": ids, "post_started": asyncio.Event()}
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            page = await browser.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))

            async def route_request(route):
                request = route.request
                parsed = urlsplit(request.url)
                path = parsed.path
                if request.method == "POST":
                    state["posts"].append((path, request.post_data_json))
                    state["post_started"].set()
                    if state.get("release"):
                        await state["release"].wait()
                    await route.fulfill(body='{"ok":true,"message":"Поиск запущен"}', content_type="application/json")
                elif path.startswith("/static/") and (ROOT / f"app/web{path}").is_file():
                    await route.fulfill(path=str(ROOT / f"app/web{path}"))
                elif path == "/api/scan/preview":
                    credits = int(parse_qs(parsed.query).get("max_credits", [5])[0])
                    payload = {**preview, "requested_credits": credits, "effective_max_credits": min(credits, 20)}
                    state["gets"].append(request.url)
                    await route.fulfill(body=json.dumps(payload), content_type="application/json")
                elif path == "/api/radar/feed":
                    await route.fulfill(body=json.dumps({"cycle_running": bool(state["posts"]), "hot_leads": [], "changes": []}), content_type="application/json")
                elif path in {"/radar", "/hot", "/contacts", "/leads"}:
                    response = await client.get(path + ("?" + parsed.query if parsed.query else ""))
                    assert response.status_code == 200, response.text[:250]
                    await route.fulfill(body=response.text, content_type="text/html")
                elif path.startswith("/api/"):
                    await route.fulfill(body="{}", content_type="application/json")
                else:
                    await route.fulfill(body="", content_type="application/javascript")

            await page.route("**/*", route_request)
            # Old wizard state must not hide records or rewrite the server's kind.
            await page.add_init_script("""
              sessionStorage.setItem('lr:find-leads', JSON.stringify({heat:'hot', audience:'makers', categories:['rattan']}));
              window.setInterval = () => 0;
            """
            )
            yield page, state, errors
            await browser.close()


@pytest.mark.parametrize("width", [320, 390, 800, 1440])
@pytest.mark.parametrize("path", ["/radar", "/hot"])
async def test_work_screens_fit_and_navigation_is_reachable(ux_page, width, path):
    page, _state, errors = ux_page
    await page.set_viewport_size({"width": width, "height": 900})
    await page.goto(f"http://127.0.0.1{path}")
    assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    secondary = page.locator("#more-navigation")
    if width <= 720:
        assert not await secondary.is_visible()
        box = await page.locator(".sidebar").bounding_box()
        assert box["y"] > 800 and box["y"] + box["height"] <= 901
        await page.locator("[data-more-toggle]").press("Enter")
        assert await secondary.is_visible()
        assert await secondary.get_by_role("link", name="Клиенты", exact=True).is_visible()
        await page.keyboard.press("Escape")
        assert not await secondary.is_visible()
        assert await page.locator("[data-more-toggle]").evaluate("element => element === document.activeElement")
        await page.locator("[data-more-toggle]").click()
        await secondary.get_by_role("link", name="Клиенты", exact=True).click()
        assert urlsplit(page.url).path == "/leads"
    else:
        assert await secondary.is_visible()
    assert not errors


async def test_results_use_server_filters_despite_old_wizard_state(ux_page):
    page, state, errors = ux_page
    await page.goto("http://127.0.0.1/radar")
    assert await page.locator(".find-lead-card").count() == 4
    assert not await page.locator(".find-lead-card[hidden]").count()
    assert await page.locator('.radar-filters select[name="kind"]').input_value() == ""
    await page.get_by_role("navigation", name="Показать сигналы").get_by_role("link", name="Тёплые", exact=True).click()
    assert "kind=warm" in page.url
    assert await page.locator(".find-lead-card").count() == 1
    assert "buyer-2" in await page.locator(".find-lead-card").inner_text()
    await page.get_by_role("navigation", name="Показать сигналы").get_by_role("link", name="Горячие", exact=True).click()
    assert await page.locator(".find-lead-card").count() == 3
    assert not state["posts"] and not errors


async def test_rejected_leads_stay_in_details_and_closed_leads_have_no_outreach_cta(ux_page):
    page, _state, errors = ux_page
    await page.goto("http://127.0.0.1/radar")
    assert "buyer-3" not in await page.locator(".find-lead-grid").inner_text()
    closed = page.locator(".find-lead-card").filter(has_text="buyer-4")
    assert await closed.get_by_role("link", name="Открыть карточку", exact=True).count() == 1
    assert not await closed.locator("[data-lead-take], a[href^='/hot']").count()
    details = page.locator(".signal-details")
    assert not await details.locator("table").is_visible()
    await details.locator("summary").click()
    assert "buyer-3" in await details.locator("table").inner_text()
    assert not await details.locator("tr").filter(has_text="buyer-3").locator("a[href^='/hot']").count()
    assert not await details.locator("tr").filter(has_text="buyer-4").locator("a[href^='/hot']").count()
    assert not errors


async def test_manual_scan_confirms_current_budget_and_locks_duplicate_clicks(ux_page):
    page, state, errors = ux_page
    await page.goto("http://127.0.0.1/radar")
    assert await page.locator("[data-find-leads] [data-scan]").count() == 1
    assert not await page.locator(".topbar [data-scan]").count()
    await page.locator('.scan-launch-budget > label').filter(has=page.locator('input[value="10"]')).click()
    assert await page.locator('input[name="scan_budget"][value="10"]').is_checked()
    await page.wait_for_function("[...document.querySelectorAll('[data-budget-max]')].every(el => el.textContent === '10 credits')")
    button = page.locator("[data-find-leads] [data-scan]")
    await button.click()
    await page.locator("#confirm-text").wait_for(state="visible")
    assert "10 credits" in await page.locator("#confirm-text").inner_text()
    await page.locator("[data-confirm-cancel]").click()
    await button.wait_for(state="visible")
    await page.wait_for_function("!document.querySelector('[data-find-leads] [data-scan]').disabled")
    assert not state["posts"]
    state["release"] = asyncio.Event()
    await button.click()
    await page.locator("[data-confirm-ok]").click()
    await page.wait_for_function("document.querySelector('[data-find-leads] [data-scan]').disabled")
    await button.evaluate("element => {element.click(); element.click();}")
    await asyncio.wait_for(state["post_started"].wait(), timeout=5)
    assert state["posts"] == [("/api/scan", {"confirm_live": True, "max_credits": 10, "vertical": "FURNITURE"})]
    state["release"].set()
    assert not errors


async def test_custom_budget_and_details_are_available_without_a_wizard(ux_page):
    page, state, errors = ux_page
    await page.goto("http://127.0.0.1/radar")
    await page.locator('[data-custom-scan-budget]').fill("7")
    await page.locator('.scan-launch-budget > label').filter(has=page.locator('input[value="custom"]')).locator('b').click()
    assert await page.locator('input[name="scan_budget"][value="custom"]').is_checked()
    await page.wait_for_function("document.querySelector('[data-budget-max]').textContent === '7 credits'")
    await page.locator(".scan-more-link").click()
    assert await page.locator("#radar-budget-card").is_visible()
    assert not state["posts"] and not errors


async def test_hot_search_keeps_open_draft_and_clears_with_escape(ux_page):
    page, state, errors = ux_page
    await page.goto("http://127.0.0.1/hot")
    queue = page.locator("[data-hot-lead-id]")
    assert await queue.count() == 2
    detail = await page.locator("[data-hot-detail] h2").inner_text()
    draft = page.locator("[data-hot-draft-text]")
    await draft.fill("Мой несохранённый ответ")
    search = page.locator("[data-hot-queue-search]")
    assert not await page.locator("[data-hot-search-clear]").is_visible()
    await search.fill("buyer-1")
    assert await page.locator("[data-hot-search-clear]").is_visible()
    assert await queue.filter(visible=True).count() == 1
    assert "1 из 2" in await page.locator("[data-hot-search-status]").inner_text()
    await search.fill("нет совпадений")
    assert await page.locator("[data-hot-search-empty]").is_visible()
    assert await page.locator("[data-hot-detail] h2").inner_text() == detail
    assert await draft.input_value() == "Мой несохранённый ответ"
    await search.press("Escape")
    assert not await page.locator("[data-hot-search-clear]").is_visible()
    assert await queue.filter(visible=True).count() == 2
    assert await draft.input_value() == "Мой несохранённый ответ"
    assert not state["posts"] and not errors


async def test_reduced_motion_keeps_controls_visible_and_disables_animation(ux_page):
    page, _state, errors = ux_page
    await page.emulate_media(reduced_motion="reduce")
    await page.set_viewport_size({"width": 390, "height": 850})
    await page.goto("http://127.0.0.1/radar#find-results")
    await page.locator("[data-more-toggle]").click()
    assert await page.locator("#more-navigation").evaluate("element => getComputedStyle(element).animationName") == "none"
    assert await page.locator("[data-find-leads] [data-scan]").evaluate("element => getComputedStyle(element).transitionDuration") == "0s"
    assert not await page.locator('[data-reveal]:not(.is-visible)').count()
    assert not errors

@pytest.mark.parametrize('width', [360, 390, 760, 1184, 1440])
async def test_custom_scan_budget_stays_inside_its_option_at_all_breakpoints(ux_page, width):
    page, state, errors = ux_page
    await page.set_viewport_size({'width': width, 'height': 844})
    await page.goto('http://127.0.0.1/radar')
    custom = page.locator('[data-custom-scan-budget]')
    await custom.fill('150')
    assert await page.locator('input[name="scan_budget"][value="custom"]').is_checked()
    # This fixture caps the effective server budget at 20; the requested input
    # still has to select the custom option and reach the preview unchanged.
    await page.wait_for_function("document.querySelector('[data-budget-max]').textContent === '20 credits'")
    assert any(parse_qs(urlsplit(url).query).get('max_credits') == ['150'] for url in state['gets'])
    bounds = await custom.evaluate('''input => {
      const inner = input.getBoundingClientRect(); const outer = input.closest('label').getBoundingClientRect();
      return {left: inner.left >= outer.left, right: inner.right <= outer.right + 1,
              fitsPage: document.documentElement.scrollWidth <= innerWidth + 1};
    }''')
    assert all(bounds.values()), bounds
    assert not state['posts'] and not errors
