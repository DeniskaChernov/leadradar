"""HOT controls and actual template layout in Chromium, with every request mocked."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
import pytest_asyncio
from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.async_api import async_playwright

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def render_hot(*, count=40, sent=False, writable=True, notice="", generation=True):
    environment = Environment(
        loader=FileSystemLoader(PROJECT_ROOT / "app/web/templates"),
        autoescape=select_autoescape(["html"]),
    )
    environment.globals.update(
        lead_status_label=lambda value: value,
        intent_label=lambda value: value,
        product_label=lambda value: value,
    )
    selected = {
        "lead_id": 1, "username": "hot_user", "score": 91,
        "status": "OFFER_SENT" if sent else "NEW", "intent": "PRICE",
        "product_category": "furniture", "contact_id": 1,
        "profile_url": "https://www.instagram.com/hot_user/",
        "post_url": "https://www.instagram.com/p/example/",
        "comment_text": "Цена? " + "LongPublicComment" * 150,
        "competitor": "seller", "ai_reason": "Прямой вопрос о цене",
        "recommendation": {"title": "Уточнить запрос", "description": "Спросите размер"},
        "draft": {"message": "Сохранённый текст", "sent_at": "2026-10-07" if sent else None},
        "already_sent": sent, "can_save_draft": writable and not sent,
        "can_prepare": writable and not sent,
    }
    return environment.get_template("hot.html").render(
        csrf_token="offline-test", safe_mode=True,
        settings=SimpleNamespace(instagram_max_units_per_scan=5, web_auth_enabled=False),
        active_path="/hot", selected_vertical="FURNITURE", search_paused=False,
        snapshot=SimpleNamespace(last_error="", cycle_running=False, progress={}),
        openai_spend_allowed=generation, openai_usage={"used": 1, "limit": 25, "remaining": 24},
        selected=selected if count else None, selection_notice=notice,
        queue_total=count, queue_page=1, queue_pages=1,
        queue=[{
            "lead_id": index, "username": f"hot_{index}", "score": 91,
            "comment_preview": "Цена на этот комплект? Нужен срочно", "competitor": "seller",
            "status": "NEW", "already_contacted": False,
        } for index in range(1, count + 1)],
    )


@pytest_asyncio.fixture
async def hot_page():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.add_init_script("""window.setInterval = () => 0;
          Object.defineProperty(navigator, 'serviceWorker', {value: {register: async () => ({})}});
        """)
        state = {"count": 40, "sent": False, "writable": True, "status": 200,
                 "posts": [], "deferred": {}, "invalid_response": False, "notice": "",
                 "generation": True, "response_detail": None}
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))

        async def route_request(route):
            path = urlsplit(route.request.url).path
            if path == "/hot":
                await route.fulfill(content_type="text/html", body=render_hot(
                    count=state["count"], sent=state["sent"], writable=state["writable"],
                    notice=state["notice"], generation=state["generation"],
                ))
                return
            if path == "/static/app.css":
                await route.fulfill(content_type="text/css", body=(
                    PROJECT_ROOT / "app/web/static/app.css"
                ).read_text(encoding="utf-8"))
                return
            if path == "/static/app.js":
                await route.fulfill(content_type="text/javascript", body=(
                    PROJECT_ROOT / "app/web/static/app.js"
                ).read_text(encoding="utf-8"))
                return
            if path.startswith("/api/hot/") and route.request.method == "POST":
                action = path.rsplit("/", 1)[-1]
                payload = route.request.post_data_json
                state["posts"].append((action, payload))
                if action in state["deferred"]:
                    await state["deferred"][action]
                if state["invalid_response"]:
                    await route.fulfill(content_type="text/html", body="<html>Bad gateway</html>")
                    return
                if state["status"] != 200:
                    await route.fulfill(status=state["status"], content_type="application/json",
                                        body=json.dumps({"detail": "Соединение прервано"}))
                    return
                text = payload.get("message") or "Подготовленный текст"
                await route.fulfill(content_type="application/json", body=json.dumps({
                    "ok": True, "message": "Текст сохранён", "next_url": "/hot?lead_id=2",
                    "detail": state["response_detail"] if state["response_detail"] is not None else {"lead_id": 1, "draft": {"message": text, "sent_at": "today" if action == "sent" else None},
                               "already_sent": action == "sent", "can_prepare": action != "sent",
                               "can_save_draft": action != "sent", "next_lead_id": 2},
                }))
                return
            if path.startswith("/api/"):
                await route.fulfill(content_type="application/json", body=json.dumps({
                    "cycle_running": False, "hot_count": 40, "changes": [], "hot_leads": [],
                }))
                return
            await route.fulfill(body="", content_type="text/plain")

        await page.route("**/*", route_request)
        await page.goto("http://127.0.0.1/hot")
        await page.wait_for_function("document.querySelector('[data-hot-workspace]').hasAttribute('aria-busy')")
        yield page, state, errors
        for future in state["deferred"].values():
            if not future.done():
                future.set_result(None)
        await browser.close()


@pytest.mark.parametrize("width", [390, 800, 1024, 1440])
async def test_hot_full_queue_never_clips_detail_or_overflows_viewport(hot_page, width):
    page, _state, errors = hot_page
    await page.set_viewport_size({"width": width, "height": 800})
    layout = await page.evaluate("""() => {
      const root = document.querySelector('.hot-workspace');
      const detail = document.querySelector('.hot-detail');
      const queue = document.querySelector('[data-hot-queue]');
      const r = root.getBoundingClientRect(), d = detail.getBoundingClientRect();
      return {width: document.documentElement.scrollWidth, viewport: innerWidth,
        rootBottom: r.bottom, detailBottom: d.bottom, queueHeight: queue.clientHeight,
        queueScroll: queue.scrollHeight, queueLimit: innerWidth <= 900 ? 280 : Math.min(innerHeight * .7, 820)};
    }""")
    assert layout["width"] <= layout["viewport"]
    assert layout["detailBottom"] <= layout["rootBottom"] + 1
    assert layout["queueHeight"] <= layout["queueLimit"] + 1
    assert layout["queueScroll"] > layout["queueHeight"]
    sent_button = page.locator("[data-hot-sent]")
    await sent_button.scroll_into_view_if_needed()
    assert await sent_button.is_visible()
    assert await sent_button.evaluate("el => {const r = el.getBoundingClientRect(); return r.top >= 0 && r.bottom <= innerHeight;}")
    assert not errors


async def test_selected_queue_card_is_visible_and_visually_identified(hot_page):
    page, _state, errors = hot_page
    active = page.locator(".hot-queue-item.is-active")
    assert await active.get_attribute("aria-current") == "true"
    assert await active.evaluate("el => getComputedStyle(el).backgroundColor") != await page.locator(
        ".hot-queue-item:not(.is-active)"
    ).first.evaluate("el => getComputedStyle(el).backgroundColor")
    assert not errors


@pytest.mark.parametrize("width", [390, 1440])
async def test_hot_empty_queue_initializes_without_error(hot_page, width):
    page, state, errors = hot_page
    state["count"] = 0
    await page.set_viewport_size({"width": width, "height": 800})
    await page.reload()
    await page.wait_for_function("document.querySelector('[data-hot-workspace]').hasAttribute('aria-busy')")
    assert await page.get_by_text("Пока некому писать", exact=True).count() == 2
    assert await page.locator("[data-hot-prepare]").count() == 0
    assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert state["posts"] == []
    assert not errors


async def test_prepare_locks_editor_and_other_mutations_until_response(hot_page):
    page, state, errors = hot_page
    state["deferred"]["prepare"] = asyncio.get_running_loop().create_future()
    await page.locator("[data-hot-prepare]").click()
    await page.wait_for_function("document.querySelector('[data-hot-workspace]').getAttribute('aria-busy') === 'true'")
    assert await page.locator("[data-hot-draft-text]").get_attribute("readonly") is not None
    assert await page.locator("[data-hot-sent]").is_disabled()
    # Input handlers must not clear the shared lock, including synthetic input.
    await page.locator("[data-hot-draft-text]").dispatch_event("input")
    await page.locator("[data-hot-prepare]").evaluate("el => el.click()")
    await page.locator("[data-hot-sent]").evaluate("el => el.click()")
    assert await page.locator("[data-hot-sent]").is_disabled()
    state["deferred"]["prepare"].set_result(None)
    await page.wait_for_function("document.querySelector('[data-hot-workspace]').getAttribute('aria-busy') === 'false'")
    assert state["posts"] == [("prepare", {})]
    assert await page.locator("[data-hot-draft-text]").input_value() == "Подготовленный текст"
    assert not errors


async def test_sent_locks_before_confirmation_and_input_cannot_duplicate_post(hot_page):
    page, state, errors = hot_page
    state["deferred"]["sent"] = asyncio.get_running_loop().create_future()
    await page.locator("[data-hot-sent]").click()
    await page.locator("#confirm.is-open [data-confirm-ok]").wait_for(state="visible")
    assert await page.locator("[data-hot-prepare]").is_disabled()
    assert await page.locator("[data-hot-draft-text]").get_attribute("readonly") is not None
    await page.locator("[data-hot-sent]").evaluate("el => el.click()")
    await page.locator("#confirm [data-confirm-ok]").click()
    await page.wait_for_timeout(250)
    await page.locator("[data-hot-draft-text]").dispatch_event("input")
    assert await page.locator("[data-hot-sent]").is_disabled()
    await page.locator("[data-hot-sent]").evaluate("el => el.click()")
    assert state["posts"] == [("sent", {"message": "Сохранённый текст"})]
    state["deferred"]["sent"].set_result(None)
    await page.wait_for_url("**/hot?lead_id=2")
    assert not errors


async def test_cancel_sent_confirmation_restores_controls_without_post(hot_page):
    page, state, errors = hot_page
    await page.locator("[data-hot-sent]").click()
    await page.locator("#confirm.is-open [data-confirm-cancel]").click()
    await page.wait_for_function("document.querySelector('[data-hot-workspace]').getAttribute('aria-busy') === 'false'")
    assert await page.locator("[data-hot-sent]").is_enabled()
    assert await page.locator("[data-hot-prepare]").is_enabled()
    assert await page.locator("[data-hot-draft-text]").get_attribute("readonly") is None
    assert state["posts"] == []
    assert not errors


async def test_manual_edits_save_explicitly_and_preparation_cannot_overwrite_them(hot_page):
    page, state, errors = hot_page
    await page.locator("[data-hot-draft-text]").fill("Новая важная правка")
    assert await page.locator("[data-hot-prepare]").is_disabled()
    assert await page.locator("[data-hot-save]").is_enabled()
    assert await page.locator("[data-hot-draft-badge]").inner_text() == "Не сохранено"
    await page.locator("[data-hot-save]").click()
    await page.wait_for_function("document.querySelector('[data-hot-draft-badge]').textContent === 'Готов'")
    assert state["posts"] == [("draft", {"message": "Новая важная правка"})]
    assert await page.locator("[data-hot-save]").is_disabled()
    assert await page.locator("[data-hot-draft-text]").input_value() == "Новая важная правка"
    assert not errors


@pytest.mark.parametrize("failure", ["409", "502", "invalid_response"])
async def test_draft_failure_retains_edit_and_releases_controls(hot_page, failure):
    page, state, errors = hot_page
    if failure == "invalid_response":
        state["invalid_response"] = True
    else:
        state["status"] = int(failure)
    await page.locator("[data-hot-draft-text]").fill("Не потеряйте этот текст")
    await page.locator("[data-hot-save]").click()
    await page.wait_for_function("document.querySelector('[data-hot-workspace]').getAttribute('aria-busy') === 'false'")
    assert await page.locator("[data-hot-draft-text]").input_value() == "Не потеряйте этот текст"
    assert await page.locator("[data-hot-save]").is_enabled()
    assert await page.locator("[data-hot-draft-badge]").inner_text() == "Не сохранено"
    assert await page.locator("#toast.bad").is_visible()
    assert len(state["posts"]) == 1
    assert not errors


async def test_dirty_navigation_can_be_cancelled_without_losing_text(hot_page):
    page, state, errors = hot_page
    await page.locator("[data-hot-draft-text]").fill("Ручной текст")
    await page.locator('[data-hot-lead-id="2"]').click()
    await page.locator("#confirm.is-open [data-confirm-cancel]").click()
    await page.wait_for_timeout(250)
    assert page.url == "http://127.0.0.1/hot"
    assert await page.locator("[data-hot-draft-text]").input_value() == "Ручной текст"
    await page.locator('[data-hot-lead-id="2"]').click()
    await page.locator("#confirm.is-open [data-confirm-ok]").click()
    await page.wait_for_url("**lead_id=2")
    assert state["posts"] == []
    assert not errors


@pytest.mark.parametrize("sent", [True, False])
async def test_read_only_lead_keeps_copy_but_blocks_mutations(hot_page, sent):
    page, state, errors = hot_page
    state.update(sent=sent, writable=False)
    await page.reload()
    await page.wait_for_function("document.querySelector('[data-hot-workspace]').hasAttribute('aria-busy')")
    assert await page.locator("[data-hot-draft-text]").get_attribute("readonly") is not None
    for attribute in ("prepare", "save", "sent"):
        assert await page.locator(f"[data-hot-{attribute}]").is_disabled()
    assert await page.locator("[data-hot-copy]").is_enabled()
    assert state["posts"] == []
    assert not errors


async def test_invalid_selection_notice_is_rendered(hot_page):
    page, state, errors = hot_page
    state["notice"] = "Этот лид уже отправлен. Открыт следующий HOT."
    await page.reload()
    assert await page.locator(".hot-selection-notice[role='status']").inner_text() == state["notice"]
    assert not errors


async def test_manual_save_cannot_enable_disabled_gpt_generation(hot_page):
    page, state, errors = hot_page
    state["generation"] = False
    await page.reload()
    await page.wait_for_function("document.querySelector('[data-hot-workspace]').hasAttribute('aria-busy')")
    await page.locator("[data-hot-draft-text]").fill("Ручной текст без GPT")
    await page.locator("[data-hot-save]").click()
    await page.wait_for_function("document.querySelector('[data-hot-draft-badge]').textContent === 'Готов'")
    assert await page.locator("[data-hot-prepare]").is_disabled()
    assert state["posts"] == [("draft", {"message": "Ручной текст без GPT"})]
    assert not errors


@pytest.mark.parametrize("detail", [{}, {"lead_id": 1}, {"lead_id": 1, "draft": None},
                                    {"lead_id": 2, "draft": {"message": "Другой клиент"}}])
async def test_malformed_or_mismatched_detail_cannot_erase_manual_edit(hot_page, detail):
    page, state, errors = hot_page
    state["response_detail"] = detail
    await page.locator("[data-hot-draft-text]").fill("Сохраните мой текст")
    await page.locator("[data-hot-save]").click()
    await page.wait_for_function("document.querySelector('[data-hot-workspace]').getAttribute('aria-busy') === 'false'")
    assert await page.locator("[data-hot-draft-text]").input_value() == "Сохраните мой текст"
    assert await page.locator("[data-hot-save]").is_enabled()
    assert await page.locator("#toast.bad").is_visible()
    assert not errors


async def test_hot_timeout_keeps_text_and_never_retries_post(hot_page):
    page, state, errors = hot_page
    await page.evaluate("""() => {
      const originalFetch = window.fetch;
      window.hotMutationCalls = 0;
      window.fetch = (url, options) => {
        if (!url.startsWith('/api/hot/')) return originalFetch(url, options);
        window.hotMutationCalls += 1;
        return new Promise((_resolve, reject) => options.signal.addEventListener('abort', () =>
          reject(new DOMException('Aborted', 'AbortError'))));
      };
      const originalTimeout = window.setTimeout;
      window.setTimeout = (callback, duration, ...args) =>
        originalTimeout(callback, duration === 90000 ? 10 : duration, ...args);
    }""")
    await page.locator("[data-hot-draft-text]").fill("Текст после таймаута")
    await page.locator("[data-hot-save]").click()
    await page.wait_for_function("document.querySelector('[data-hot-workspace]').getAttribute('aria-busy') === 'false'")
    assert await page.locator("[data-hot-draft-text]").input_value() == "Текст после таймаута"
    assert await page.locator("[data-hot-save]").is_enabled()
    assert "действие могло выполниться" in await page.locator("[data-toast-message]").inner_text()
    assert await page.evaluate("window.hotMutationCalls") == 1
    assert state["posts"] == []
    assert not errors
