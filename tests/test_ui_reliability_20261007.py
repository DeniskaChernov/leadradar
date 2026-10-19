"""Execute production JavaScript in Chromium with every HTTP request mocked."""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

import pytest
import pytest_asyncio
from playwright.async_api import async_playwright

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (PROJECT_ROOT / "app/web/static/app.js").read_text(encoding="utf-8")
# Expose closures only in the test copy; deployed JavaScript has no test API.
SCRIPT = SCRIPT.rsplit("})();", 1)[0] + """
  window.uiTest = { api, enhanceMotion, applyScanProgress, runScan, reloadSoon, restoreViewState, authReturnTarget,
    pollRadarFeed, pollScanProgress, notePollingFailure, notePollingSuccess,
    syncScanButtonsFromPreview, refreshScanBudgetPreview, initialRadarLayout };
})();
"""
HTML = """<!doctype html><html><head><meta charset="utf-8"></head><body data-page="/radar" data-scan-vertical="FURNITURE">
<section data-motion-root><article id="content">Комментарии и лиды</article></section>
<button id="scan-main" data-scan>Найти лидов</button>
<button id="scan-other" data-scan>Проверить сейчас</button>
<button id="scan-paused" data-scan disabled>Поиск приостановлен</button>
<div data-live-status-pill></div>
<div data-poll-connection-status hidden><span data-poll-connection-text></span>
<a data-poll-login href="/auth" hidden>Войти снова</a></div>
<div id="toast"><span data-toast-message></span></div>
</body></html>"""


@pytest_asyncio.fixture
async def ui_page():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        state = {"feed_status": 200, "scan_posts": 0, "preview_gets": 0}
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))

        async def route_request(route):
            path = urlsplit(route.request.url).path
            if path == "/ui-reliability":
                await route.fulfill(body=HTML, content_type="text/html")
                return
            if path == "/api/scan/preview":
                state["preview_gets"] += 1
                payload = {
                    "search_enabled": True, "is_live": False,
                    "can_start": True, "requested_credits": 5,
                }
            elif path == "/api/scan":
                state["scan_posts"] += 1
                payload = {"ok": True, "message": "Проверка запущена"}
            else:
                payload = {"cycle_running": False, "changes": [], "hot_leads": []}
            status = state["feed_status"] if path == "/api/radar/feed" else 200
            await route.fulfill(
                status=status, body=json.dumps(payload), content_type="application/json",
            )

        await page.route("**/*", route_request)
        await page.goto("http://127.0.0.1/ui-reliability")
        # Deterministic explicit polls; no periodic/background network in the tests.
        await page.evaluate("window.setInterval = () => 0")
        yield page, state, errors
        await browser.close()


@pytest.mark.parametrize("observer", ["missing", "constructor_error", "observe_error"])
async def test_motion_failure_keeps_content_visible_and_handlers_work(ui_page, observer):
    page, _state, errors = ui_page
    replacements = {
        "missing": "window.IntersectionObserver = undefined",
        "constructor_error": "window.IntersectionObserver = class { constructor() { throw new Error('IO'); } }",
        "observe_error": "window.IntersectionObserver = class { observe() { throw new Error('observe'); } disconnect() {} }",
    }
    await page.evaluate("() => { " + replacements[observer] + "; }")
    await page.add_style_tag(path=str(PROJECT_ROOT / "app/web/static/app.css"))
    await page.add_script_tag(content=SCRIPT)
    await page.wait_for_function("Boolean(window.uiTest)")
    assert await page.locator("#content").evaluate("el => getComputedStyle(el).opacity") == "1"
    assert not await page.locator("html").evaluate("el => el.classList.contains('motion-ready')")
    assert not errors


async def test_denied_storage_does_not_break_initialization(ui_page):
    page, _state, errors = ui_page
    await page.evaluate("""Object.defineProperty(window, 'sessionStorage', {
      get() { throw new DOMException('Blocked', 'SecurityError'); }
    })""")
    await page.add_script_tag(content=SCRIPT)
    await page.wait_for_function("Boolean(window.uiTest)")
    assert not errors


async def test_reduced_motion_does_not_hide_content(ui_page):
    page, _state, errors = ui_page
    await page.emulate_media(reduced_motion="reduce")
    await page.add_style_tag(path=str(PROJECT_ROOT / "app/web/static/app.css"))
    await page.add_script_tag(content=SCRIPT)
    assert await page.locator("#content").evaluate("el => getComputedStyle(el).opacity") == "1"
    assert not await page.locator("html").evaluate("el => el.classList.contains('motion-ready')")
    assert not errors


@pytest.mark.parametrize("reduced_motion", ["reduce", "no-preference"])
async def test_scroll_position_is_saved_and_restored_without_animation(ui_page, reduced_motion):
    page, _state, errors = ui_page
    await page.emulate_media(reduced_motion=reduced_motion)
    await page.add_script_tag(content=SCRIPT)
    saved = await page.evaluate("""() => {
      document.body.style.minHeight = '3000px';
      window.scrollTo(0, 650);
      uiTest.reloadSoon(60000);
      const saved = sessionStorage.getItem('lr:scroll-y');
      window.scrollTo(0, 0);
      uiTest.restoreViewState();
      return saved;
    }""")
    assert saved == "650"
    await page.wait_for_function("window.scrollY === 650")
    assert await page.evaluate("sessionStorage.getItem('lr:scroll-y')") is None
    assert not errors


async def test_api_timeout_aborts_one_mutation_and_returns_clear_message(ui_page):
    page, _state, _errors = ui_page
    await page.add_script_tag(content=SCRIPT)
    result = await page.evaluate("""async () => {
      let calls = 0;
      let aborted = false;
      window.fetch = (_url, options) => {
        calls += 1;
        return new Promise((_resolve, reject) => {
          options.signal.addEventListener('abort', () => {
            aborted = true;
            reject(new DOMException('Aborted', 'AbortError'));
          });
        });
      };
      let message = '';
      try { await uiTest.api('/api/scan', {method: 'POST', body: '{}', timeoutMs: 10}); }
      catch (error) { message = error.message; }
      return {calls, aborted, message};
    }""")
    assert result["calls"] == 1
    assert result["aborted"] is True
    assert "действие могло выполниться" in result["message"]


async def test_cloudflare_html_error_is_not_dumped_into_user_message(ui_page):
    page, _state, _errors = ui_page
    await page.add_script_tag(content=SCRIPT)
    message = await page.evaluate("""async () => {
      window.fetch = async () => new Response('<html><script>error page</script></html>',
        {status: 502, headers: {'Content-Type': 'text/html'}});
      try { await uiTest.api('/api/scan/progress'); }
      catch (error) { return error.message; }
    }""")
    assert "502" in message
    assert "<html>" not in message


async def test_poll_disconnect_and_recovery_are_visible(ui_page):
    page, state, _errors = ui_page
    await page.add_script_tag(content=SCRIPT)
    # Manual polls coalesce with startup. Set failure state only after that
    # real initial request settles, so two calls represent two failed requests.
    await page.evaluate("uiTest.initialRadarLayout")
    await page.evaluate("uiTest.pollRadarFeed()")
    state["feed_status"] = 502
    await page.evaluate("uiTest.pollRadarFeed()")
    await page.evaluate("uiTest.pollRadarFeed()")
    assert await page.locator("[data-poll-connection-status]").is_visible()
    assert "последние полученные данные" in await page.locator("[data-poll-connection-text]").inner_text()
    assert await page.locator("[data-poll-login]").is_hidden()
    state["feed_status"] = 200
    await page.evaluate("uiTest.pollRadarFeed()")
    assert await page.locator("[data-poll-connection-status]").is_hidden()


async def test_expired_session_has_login_action(ui_page):
    page, state, _errors = ui_page
    await page.add_script_tag(content=SCRIPT)
    await page.evaluate("uiTest.initialRadarLayout")
    await page.evaluate("uiTest.pollRadarFeed()")
    state["feed_status"] = 401
    await page.evaluate("uiTest.pollRadarFeed()")
    assert "Сессия истекла" in await page.locator("[data-poll-connection-text]").inner_text()
    assert await page.locator("[data-poll-login]").is_visible()


async def test_disconnect_after_delayed_initial_poll_recovers(ui_page):
    page, state, errors = ui_page
    initial_started = asyncio.Event()
    release_initial = asyncio.Event()
    requests = 0

    async def delayed_feed(route):
        nonlocal requests
        requests += 1
        status = state["feed_status"]
        if requests == 1:
            initial_started.set()
            await release_initial.wait()
        await route.fulfill(
            status=status, body=json.dumps({"cycle_running": False, "changes": [], "hot_leads": []}),
            content_type="application/json",
        )

    await page.route("**/api/radar/feed?*", delayed_feed)
    await page.add_script_tag(content=SCRIPT)
    await initial_started.wait()
    state["feed_status"] = 502
    await page.evaluate("uiTest.pollRadarFeed()")
    assert requests == 1  # No overlapping request while startup is pending.
    release_initial.set()
    await page.evaluate("uiTest.initialRadarLayout")
    await page.evaluate("uiTest.pollRadarFeed()")
    await page.evaluate("uiTest.pollRadarFeed()")
    assert await page.locator("[data-poll-connection-status]").is_visible()
    state["feed_status"] = 200
    await page.evaluate("uiTest.pollRadarFeed()")
    assert await page.locator("[data-poll-connection-status]").is_hidden()
    assert errors == []


async def test_scan_start_is_locked_and_progress_survives_post_response(ui_page):
    page, _state, _errors = ui_page
    await page.add_script_tag(content=SCRIPT)
    result = await page.evaluate("""async () => {
      const originalFetch = window.fetch;
      let releaseScan;
      let scanCalls = 0;
      window.fetch = (url, options) => {
        if (url !== '/api/scan') return originalFetch(url, options);
        scanCalls += 1;
        return new Promise(resolve => { releaseScan = resolve; });
      };
      const main = document.querySelector('#scan-main');
      const other = document.querySelector('#scan-other');
      const first = uiTest.runScan(main, 5);
      while (!releaseScan) await new Promise(resolve => setTimeout(resolve, 1));
      const otherLocked = other.disabled;
      uiTest.syncScanButtonsFromPreview({search_enabled: true, is_live: false});
      const previewKeptLock = other.disabled;
      await uiTest.runScan(other, 5);
      uiTest.applyScanProgress({cycle_running: true, progress: {percent: 42}});
      releaseScan(new Response(JSON.stringify({ok: false, message: 'Проверка уже выполняется'}),
        {headers: {'Content-Type': 'application/json'}}));
      await first;
      const progressKept = main.disabled && main.textContent === 'Проверка 42%';
      uiTest.applyScanProgress({cycle_running: false});
      return {scanCalls, otherLocked, previewKeptLock, progressKept,
        normalEnabled: !main.disabled, pausedDisabled: document.querySelector('#scan-paused').disabled,
        restoredLabel: main.textContent};
    }""")
    assert result == {
        "scanCalls": 1, "otherLocked": True, "previewKeptLock": True,
        "progressKept": True, "normalEnabled": True, "pausedDisabled": True,
        "restoredLabel": "Найти лидов",
    }


async def test_idle_progress_does_not_poll_budget_repeatedly(ui_page):
    page, state, _errors = ui_page
    await page.add_script_tag(content=SCRIPT)
    before = state["preview_gets"]
    await page.evaluate("""() => {
      for (let i = 0; i < 20; i += 1) uiTest.applyScanProgress({cycle_running: false});
    }""")
    assert state["preview_gets"] == before


async def test_scan_timeout_refreshes_state_without_reposting(ui_page):
    page, _state, _errors = ui_page
    await page.add_script_tag(content=SCRIPT)
    await page.evaluate("uiTest.pollRadarFeed()")
    result = await page.evaluate("""async () => {
      const originalTimer = window.setTimeout;
      window.setTimeout = (callback, delay) => originalTimer(callback, delay === 90000 ? 10 : delay);
      let posts = 0;
      let refreshed = 0;
      window.fetch = (url, options) => {
        if (url === '/api/scan') {
          posts += 1;
          return new Promise((_resolve, reject) => {
            options.signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')));
          });
        }
        let payload = {search_enabled: true, is_live: false};
        if (String(url).includes('/api/radar/feed')) {
          refreshed += 1;
          payload = {cycle_running: true, progress: {percent: 37}, hot_leads: [], changes: []};
        }
        return Promise.resolve(new Response(JSON.stringify(payload),
          {headers: {'Content-Type': 'application/json'}}));
      };
      const button = document.querySelector('#scan-main');
      await uiTest.runScan(button, 5);
      return {posts, refreshed, disabled: button.disabled, label: button.textContent};
    }""")
    assert result == {"posts": 1, "refreshed": 1, "disabled": True, "label": "Проверка 37%"}


async def test_fast_accepted_scan_still_shows_completion(ui_page):
    page, _state, _errors = ui_page
    await page.add_script_tag(content=SCRIPT)
    await page.evaluate("uiTest.pollRadarFeed()")
    await page.evaluate("""async () => {
      await uiTest.runScan(document.querySelector('#scan-main'), 5);
      await new Promise(resolve => setTimeout(resolve, 20));
      await uiTest.pollRadarFeed();
    }""")
    assert "Поиск завершён" in await page.locator("[data-toast-message]").inner_text()


@pytest.mark.parametrize("run_id", [77, None, "https://untrusted.example/"])
async def test_scan_summary_links_open_that_saved_search_and_its_source_views(ui_page, run_id):
    page, state, errors = ui_page
    await page.locator('#content').evaluate("""element => {
      element.insertAdjacentHTML('afterend', `<div id="scan-summary" hidden>
        <p data-scan-summary-subtitle></p>
        <a data-scan-summary-results="leads"></a><a data-scan-summary-results="companies"></a>
        <a data-scan-summary-results="posts"></a><a data-scan-summary-results="comments"></a>
        <button data-scan-summary-ok>Понятно</button></div>`);
    }""")
    running = True

    async def feed(route):
        await route.fulfill(content_type="application/json", body=json.dumps({
            "cycle_running": running, "last_run_id": run_id,
            "last_stats": {"comments_created": 5, "leads_created": 4},
            "changes": [], "hot_leads": [],
        }))

    await page.route("**/api/radar/feed?*", feed)
    await page.add_script_tag(content=SCRIPT)
    await page.wait_for_function("document.querySelector('#scan-main').dataset.scanBusy === '1'")
    running = False
    await page.evaluate("uiTest.pollRadarFeed()")
    await page.wait_for_function("!document.querySelector('#scan-summary').hidden")
    for view in ("leads", "companies", "posts", "comments"):
        target = urlsplit(await page.locator(f'[data-scan-summary-results="{view}"]').get_attribute('href'))
        assert target.path == ("/searches/77" if run_id == 77 else "/searches")
        if run_id == 77:
            assert f"view={view}" in target.query
        assert "vertical=FURNITURE" in target.query
    assert state["scan_posts"] == 0 and not errors


@pytest.mark.parametrize("active_page", ["/radar", "/hot"])
async def test_scan_ignores_delayed_status_from_before_accepted_post(ui_page, active_page):
    page, state, errors = ui_page
    await page.locator("body").evaluate("(el, value) => el.dataset.page = value", active_page)
    await page.evaluate("""() => {
      window.scanMessages = [];
      new MutationObserver(() => {
        scanMessages.push(document.querySelector('[data-toast-message]').textContent);
      }).observe(document.querySelector('[data-toast-message]'), {childList: true});
    }""")
    first_started = asyncio.Event()
    release_stale = asyncio.Event()
    status_gets = 0

    async def delayed_status(route):
        nonlocal status_gets
        status_gets += 1
        if status_gets == 1:
            first_started.set()
            await release_stale.wait()
            payload = {
                "cycle_running": False, "cycles_completed": 1,
                "last_stats": {"comments_created": 111, "leads_created": 88},
                "changes": [], "hot_leads": [],
            }
        else:
            payload = {
                "cycle_running": True, "cycles_completed": 1,
                "progress": {"percent": 42}, "scan_progress": {"percent": 42},
                "changes": [], "hot_leads": [],
            }
        await route.fulfill(body=json.dumps(payload), content_type="application/json")

    pattern = "**/api/radar/feed?*" if active_page == "/radar" else "**/api/scan/progress"
    await page.route(pattern, delayed_status)
    await page.add_script_tag(content=SCRIPT)
    await first_started.wait()
    await page.evaluate("uiTest.runScan(document.querySelector('#scan-main'), 5)")
    assert await page.locator("#scan-main").is_disabled()
    assert state["scan_posts"] == 1
    release_stale.set()
    await page.wait_for_function("document.querySelector('#scan-main').textContent === 'Проверка 42%'")
    assert await page.locator("#scan-main").is_disabled()
    messages = await page.evaluate("window.scanMessages")
    assert not any("Поиск завершён" in message for message in messages)
    assert not any("111" in message or "88 лидов" in message for message in messages)
    assert status_gets == 2
    assert not errors


async def test_budget_preview_only_applies_latest_selection(ui_page):
    page, _state, errors = ui_page
    await page.add_script_tag(content=SCRIPT)
    await page.locator("#content").evaluate("""el => {
      el.innerHTML = '<input type="radio" name="scan_budget" value="5" checked>'
        + '<span data-budget-max></span>';
    }""")
    result = await page.evaluate("""async () => {
      let releaseOld;
      window.fetch = url => {
        if (String(url).includes('max_credits=5')) return new Promise(resolve => { releaseOld = resolve; });
        return Promise.resolve(new Response(JSON.stringify({
          effective_max_credits: 10, search_enabled: false, is_live: false
        }), {headers: {'Content-Type': 'application/json'}}));
      };
      const root = document.querySelector('#content');
      const old = uiTest.refreshScanBudgetPreview(root);
      while (!releaseOld) await new Promise(resolve => setTimeout(resolve, 1));
      root.querySelector('input').value = '10';
      await uiTest.refreshScanBudgetPreview(root);
      releaseOld(new Response(JSON.stringify({effective_max_credits: 5, search_enabled: true, is_live: false}),
        {headers: {'Content-Type': 'application/json'}}));
      await old;
      return {maximum: root.querySelector('[data-budget-max]').textContent,
        disabled: document.querySelector('#scan-main').disabled};
    }""")
    assert result == {"maximum": "10 credits", "disabled": True}
    assert not errors


async def test_scan_ignores_status_started_while_post_was_pending(ui_page):
    page, _state, errors = ui_page
    await page.add_script_tag(content=SCRIPT)
    await page.evaluate("uiTest.pollRadarFeed()")
    result = await page.evaluate("""async () => {
      const originalFetch = window.fetch;
      let releasePost;
      let releaseStaleStatus;
      let statusGets = 0;
      window.fetch = (url, options) => {
        if (url === '/api/scan') return new Promise(resolve => { releasePost = resolve; });
        if (String(url).includes('/api/radar/feed')) {
          statusGets += 1;
          if (statusGets === 1) return new Promise(resolve => { releaseStaleStatus = resolve; });
          return Promise.resolve(new Response(JSON.stringify({
            cycle_running: true, scan_progress: {percent: 42}, hot_leads: [], changes: []
          }), {headers: {'Content-Type': 'application/json'}}));
        }
        return originalFetch(url, options);
      };
      const button = document.querySelector('#scan-main');
      const scan = uiTest.runScan(button, 5);
      while (!releasePost) await new Promise(resolve => setTimeout(resolve, 1));
      const status = uiTest.pollRadarFeed();
      while (!releaseStaleStatus) await new Promise(resolve => setTimeout(resolve, 1));
      releasePost(new Response(JSON.stringify({ok: true, message: 'Проверка запущена'}),
        {headers: {'Content-Type': 'application/json'}}));
      await scan;
      const acceptedLocked = button.disabled;
      releaseStaleStatus(new Response(JSON.stringify({
        cycle_running: false, last_stats: {comments_created: 111, leads_created: 88}, hot_leads: [], changes: []
      }), {headers: {'Content-Type': 'application/json'}}));
      await status;
      while (button.textContent !== 'Проверка 42%') await new Promise(resolve => setTimeout(resolve, 1));
      return {acceptedLocked, statusGets, label: button.textContent, disabled: button.disabled,
        toast: document.querySelector('[data-toast-message]').textContent};
    }""")
    assert result == {
        "acceptedLocked": True, "statusGets": 2, "label": "Проверка 42%",
        "disabled": True, "toast": "Проверка запущена",
    }
    assert not errors


async def test_idle_status_during_pending_post_does_not_change_task_state(ui_page):
    page, _state, errors = ui_page
    await page.add_script_tag(content=SCRIPT)
    await page.evaluate("uiTest.pollRadarFeed()")
    result = await page.evaluate("""async () => {
      const originalFetch = window.fetch;
      let releasePost;
      let statusGets = 0;
      window.fetch = (url, options) => {
        if (url === '/api/scan') return new Promise(resolve => { releasePost = resolve; });
        if (String(url).includes('/api/radar/feed')) {
          statusGets += 1;
          return Promise.resolve(new Response(JSON.stringify(statusGets === 1 ? {
            cycle_running: false, last_stats: {comments_created: 111, leads_created: 88}, hot_leads: [], changes: []
          } : {
            cycle_running: true, scan_progress: {percent: 42}, hot_leads: [], changes: []
          }), {headers: {'Content-Type': 'application/json'}}));
        }
        return originalFetch(url, options);
      };
      const button = document.querySelector('#scan-main');
      const scan = uiTest.runScan(button, 5);
      while (!releasePost) await new Promise(resolve => setTimeout(resolve, 1));
      await uiTest.pollRadarFeed();
      const pendingLabel = button.textContent;
      const pendingLocked = button.disabled && button.dataset.scanBusy === '1';
      const callsDuringPost = statusGets;
      releasePost(new Response(JSON.stringify({ok: true, message: 'Проверка запущена'}),
        {headers: {'Content-Type': 'application/json'}}));
      await scan;
      while (button.textContent !== 'Проверка 42%') await new Promise(resolve => setTimeout(resolve, 1));
      return {pendingLabel, pendingLocked, callsDuringPost, statusGets,
        label: button.textContent, disabled: button.disabled,
        toast: document.querySelector('[data-toast-message]').textContent};
    }""")
    assert result == {
        "pendingLabel": "Проверка 0%", "pendingLocked": True, "callsDuringPost": 1,
        "statusGets": 2, "label": "Проверка 42%", "disabled": True,
        "toast": "Проверка запущена",
    }
    assert not errors


async def test_keyboard_focus_is_visible_on_hidden_choice_input(ui_page):
    page, _state, _errors = ui_page
    await page.add_style_tag(path=str(PROJECT_ROOT / "app/web/static/app.css"))
    await page.locator("#content").evaluate("""el => {
      el.innerHTML = '<label class="find-chip"><input type="checkbox">Мебель</label>';
    }""")
    await page.locator(".find-chip input").focus()
    assert await page.locator(".find-chip").evaluate("el => getComputedStyle(el).outlineWidth") == "3px"


def test_asset_cache_versions_match_every_shell():
    sw = (PROJECT_ROOT / "app/web/static/sw.js").read_text(encoding="utf-8")
    version = re.search(r'const CACHE_VERSION = "([^"]+)"', sw).group(1)
    for name in ["base.html", "auth.html"]:
        template = (PROJECT_ROOT / "app/web/templates" / name).read_text(encoding="utf-8")
        assert f"app.js?v={version}" in template
        assert f"app.css?v={version}" in template
    offline = (PROJECT_ROOT / "app/web/static/offline.html").read_text(encoding="utf-8")
    assert f"app.css?v={version}" in offline

async def test_silent_motion_observer_cannot_hide_content(ui_page):
    page, _state, errors = ui_page
    await page.evaluate("() => { window.IntersectionObserver = class { observe() {} unobserve() {} disconnect() {} }; }")
    await page.add_style_tag(path=str(PROJECT_ROOT / 'app/web/static/app.css'))
    await page.add_script_tag(content=SCRIPT)
    await page.wait_for_function('Boolean(window.uiTest)')
    assert await page.locator('#content').evaluate('el => getComputedStyle(el).opacity') == '1'
    assert await page.locator('#content').evaluate('el => getComputedStyle(el).transform') == 'none'
    assert not errors


async def test_changing_reduced_motion_cancels_active_effects(ui_page):
    page, _state, errors = ui_page
    await page.emulate_media(reduced_motion='no-preference')
    await page.evaluate('''() => {
      const original = Element.prototype.animate;
      Element.prototype.animate = function(frames, options) {
        return original.call(this, frames, {...options, duration: 60000});
      };
    }''')
    await page.add_style_tag(path=str(PROJECT_ROOT / 'app/web/static/app.css'))
    await page.add_script_tag(content=SCRIPT)
    await page.wait_for_function("document.querySelector('#content').getAnimations().length > 0")
    await page.emulate_media(reduced_motion='reduce')
    await page.wait_for_function("document.querySelector('#content').getAnimations().length === 0")
    assert await page.locator('#content').evaluate('el => getComputedStyle(el).opacity') == '1'
    assert not errors


async def test_failed_animation_api_does_not_break_page_initialization(ui_page):
    page, _state, errors = ui_page
    await page.evaluate("() => { Element.prototype.animate = () => {throw new Error('Optional animation failed')}; }")
    await page.add_style_tag(path=str(PROJECT_ROOT / 'app/web/static/app.css'))
    await page.add_script_tag(content=SCRIPT)
    await page.wait_for_function('Boolean(window.uiTest)')
    assert await page.locator('#content').is_visible()
    assert await page.locator('#content').evaluate('el => getComputedStyle(el).opacity') == '1'
    assert not errors

@pytest.mark.parametrize(('target', 'expected'), [
    ('/hot?vertical=FURNITURE&page=1&lead_id=426', '/hot?vertical=FURNITURE&page=1&lead_id=426'),
    ('/radar?post=12#radar-post-results', '/radar?post=12#radar-post-results'),
    ('/auth?next=https://outside.invalid', '/radar'),
    ('/api/scan', '/radar'),
    ('//outside.invalid/path', '/radar'),
    ('javascript:alert(1)', '/radar'),
    ('http://127.0.0.1//outside.invalid/path', '//outside.invalid/path'),
])
async def test_login_return_target_retains_workspace_and_never_leaves_origin(ui_page, target, expected):
    page, _state, errors = ui_page
    await page.add_script_tag(content=SCRIPT)
    result = await page.evaluate('target => window.uiTest.authReturnTarget(target)', target)
    assert result == 'http://127.0.0.1' + expected
    assert not errors
