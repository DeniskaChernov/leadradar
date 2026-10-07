"""Real HOT/auth templates remain usable when optional CDN requests never finish."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from urllib.parse import urlsplit

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from playwright.async_api import async_playwright

from app.config import Settings
from app.db.models import Lead, LeadStatus
from app.services.contact_service import ContactService
from app.web.auth import TelegramWebAuth
from tests.e2e.helpers import build_e2e_app
from tests.test_contact_service import make_comment, make_post

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest_asyncio.fixture
async def loading_browser(session_factory):
    signal = await ContactService(session_factory).persist_signal(make_post(), make_comment())
    async with session_factory() as session:
        session.add(Lead(contact_id=signal.contact_id, comment_id=signal.comment_id,
                         competitor_id=signal.competitor_id, lead_score=85,
                         status=LeadStatus.NEW, intent="ASK_PRICE"))
        await session.commit()
    settings = Settings(
        _env_file=None, web_auth_enabled=False, web_manager_id=1001,
        web_password_hash=TelegramWebAuth.hash_password("browser-test-password"),
        instagram_provider="replay", external_kill_switch=True, openai_api_key="",
    )
    async with AsyncClient(transport=ASGITransport(app=build_e2e_app(session_factory, settings)),
                           base_url="http://test") as client:
        templates = {path: (await client.get(path)).text for path in ("/hot", "/auth")}

    state = {
        "external_started": set(), "posts": [], "telegram_body": "",
        "telegram_release": asyncio.Event(), "lucide_release": asyncio.Event(),
        "fonts_release": asyncio.Event(), "auth_release": asyncio.Event(),
        "app_release": asyncio.Event(),
    }
    state["app_release"].set()
    errors = []
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context(service_workers="block")
        page = await context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        await page.add_init_script("""Object.defineProperty(navigator, 'clipboard', {
          value: { writeText: async text => { window.copiedText = text; } }
        });
        window.swRegistrations = [];
        Object.defineProperty(navigator, 'serviceWorker', { configurable: true, value: {
          register: (url, options) => {
            window.swRegistrations.push({url, options});
            if (window.swFailure === 'throw') throw new Error('Offline shell unavailable');
            if (window.swFailure === 'rejected') return Promise.reject(new Error('Offline shell unavailable'));
            return Promise.resolve({scope: options.scope});
          }
        }});""")

        async def route_request(route):
            url = urlsplit(route.request.url)
            if url.hostname == "telegram.org":
                state["external_started"].add("telegram")
                await state["telegram_release"].wait()
                await route.fulfill(body=state["telegram_body"],
                                    content_type="application/javascript")
            elif url.hostname == "unpkg.com":
                state["external_started"].add("lucide")
                await state["lucide_release"].wait()
                await route.fulfill(body="window.lucide = {createIcons: () => { "
                                        "window.iconInitCount = (window.iconInitCount || 0) + 1; }};",
                                    content_type="application/javascript")
            elif url.hostname in {"fonts.googleapis.com", "fonts.gstatic.com"}:
                state["external_started"].add("fonts")
                await state["fonts_release"].wait()
                await route.fulfill(body="/* Optional font stylesheet */", content_type="text/css")
            elif url.path in templates:
                await route.fulfill(body=templates[url.path], content_type="text/html")
            elif url.path.startswith("/static/"):
                if url.path == "/static/app.js":
                    await state["app_release"].wait()
                path = PROJECT_ROOT / "app/web" / url.path.lstrip("/")
                if not path.is_file():
                    await route.fulfill(status=404, body="")
                    return
                mime = {".js": "application/javascript", ".css": "text/css", ".svg": "image/svg+xml"}
                await route.fulfill(body=path.read_bytes(),
                                    content_type=mime.get(path.suffix, "application/octet-stream"))
            else:
                if route.request.method == "POST":
                    state["posts"].append((url.path, route.request.post_data_json))
                status = 200
                data = {"cycle_running": False, "changes": [], "hot_leads": []}
                if url.path == "/api/auth/password":
                    status, data = 401, {"detail": "Неверный пароль."}
                elif url.path == "/api/auth/telegram":
                    await state["auth_release"].wait()
                    status, data = 401, {"detail": "Нет доступа в тесте"}
                await route.fulfill(status=status, body=json.dumps(data),
                                    content_type="application/json")

        await page.route("**/*", route_request)
        try:
            yield page, state, errors
        finally:
            for key in ("telegram_release", "lucide_release", "fonts_release", "auth_release", "app_release"):
                state[key].set()
            # Let intercepted requests settle before their browser context closes.
            await asyncio.sleep(0.05)
            await browser.close()


async def test_hot_renders_and_manual_buttons_work_with_all_cdns_pending(loading_browser):
    page, state, errors = loading_browser
    await page.goto("http://127.0.0.1/hot", wait_until="domcontentloaded", timeout=3000)
    await page.locator("[data-hot-workspace]").wait_for(state="visible", timeout=1500)
    draft = page.locator("[data-hot-draft-text]")
    await draft.fill("Здравствуйте! Подскажите, сколько стульев вам нужно?")
    await page.wait_for_function("!document.querySelector('[data-hot-copy]').disabled")
    await page.locator("[data-hot-copy]").click()
    assert await page.evaluate("window.copiedText") == await draft.input_value()
    await page.locator("button[data-hot-sent]").click()
    await page.locator("#confirm").wait_for(state="visible")
    await page.locator("[data-confirm-cancel]").click()
    assert state["external_started"] == {"telegram", "lucide", "fonts"}
    assert await page.evaluate("window.swRegistrations") == [{"url": "/sw.js", "options": {"scope": "/"}}]
    assert not any(path.endswith(("/prepare", "/sent")) for path, _ in state["posts"])
    assert not errors


async def test_password_login_works_before_telegram_and_fonts_finish(loading_browser):
    page, state, errors = loading_browser
    await page.goto("http://127.0.0.1/auth", wait_until="domcontentloaded", timeout=3000)
    await page.get_by_label("Пароль доступа").fill("incorrect-password")
    await page.get_by_role("button", name="Войти в Lead Radar").click()
    await page.get_by_text("Неверный пароль.", exact=True).wait_for(timeout=1500)
    assert state["posts"] == [("/api/auth/password", {"password": "incorrect-password"})]
    assert not await page.locator("html").evaluate("el => el.classList.contains('inside-telegram')")
    assert not errors


async def test_late_icons_and_fonts_initialize_without_blocking_hot(loading_browser):
    page, state, errors = loading_browser
    await page.goto("http://127.0.0.1/hot", wait_until="domcontentloaded", timeout=3000)
    assert await page.locator("#optional-fonts").get_attribute("media") == "print"
    state["lucide_release"].set()
    state["fonts_release"].set()
    await page.wait_for_function("document.documentElement.classList.contains('icons-ready')")
    await page.wait_for_function("document.getElementById('optional-fonts').media === 'all'")
    assert await page.evaluate("window.iconInitCount") == 1
    assert not errors


async def test_late_telegram_auth_initializes_once_and_deduplicates_requests(loading_browser):
    page, state, errors = loading_browser
    await page.goto("http://127.0.0.1/auth", wait_until="domcontentloaded", timeout=3000)
    state["telegram_body"] = """window.telegramCalls = [];
    window.Telegram = {WebApp: {
      initData: 'test-telegram-payload', colorScheme: 'light',
      isVersionAtLeast: () => false,
      ready: () => window.telegramCalls.push('ready'),
      expand: () => window.telegramCalls.push('expand'),
      setHeaderColor: () => window.telegramCalls.push('unsupported-header'),
      setBackgroundColor: () => window.telegramCalls.push('unsupported-background'),
      disableVerticalSwipes: () => window.telegramCalls.push('unsupported-swipes')
    }};"""
    state["telegram_release"].set()
    await page.wait_for_function("document.documentElement.classList.contains('inside-telegram')")
    await page.evaluate("document.getElementById('telegram-sdk').dispatchEvent(new Event('load'))")
    await page.evaluate("document.getElementById('telegram-sdk').dispatchEvent(new Event('load'))")
    await page.wait_for_function("document.getElementById('auth-status').textContent === 'Проверяем доступ…'")
    assert await page.evaluate("window.telegramCalls") == ["ready", "expand"]
    assert state["posts"] == [("/api/auth/telegram", {"initData": "test-telegram-payload"})]
    state["auth_release"].set()
    await page.get_by_text("Нет доступа в тесте", exact=True).wait_for(timeout=1500)
    await page.locator("[data-auth-retry]").click()
    await page.wait_for_function("document.getElementById('auth-status').textContent === 'Нет доступа в тесте'")
    assert len(state["posts"]) == 2
    assert not errors


async def test_normal_browser_sdk_does_not_apply_telegram_styles(loading_browser):
    page, state, errors = loading_browser
    await page.goto("http://127.0.0.1/hot", wait_until="domcontentloaded", timeout=3000)
    state["telegram_body"] = """window.Telegram = {WebApp: {
      initData: '', ready: () => { throw new Error('Should not initialize'); }
    }};"""
    state["telegram_release"].set()
    await page.wait_for_function("Boolean(window.Telegram)")
    assert not await page.locator("html").evaluate("el => el.classList.contains('inside-telegram')")
    assert not errors


async def test_icons_and_fonts_loaded_before_app_still_initialize(loading_browser):
    page, state, errors = loading_browser
    state["app_release"].clear()
    state["lucide_release"].set()
    state["fonts_release"].set()
    await page.goto("http://127.0.0.1/hot", wait_until="commit")
    await page.wait_for_function("Boolean(window.lucide) && Boolean(document.getElementById('optional-fonts').sheet)")
    assert await page.locator("#optional-fonts").get_attribute("media") == "print"
    assert not await page.locator("html").evaluate("el => el.classList.contains('icons-ready')")
    state["app_release"].set()
    await page.wait_for_function("document.documentElement.classList.contains('icons-ready')")
    await page.wait_for_function("document.getElementById('optional-fonts').media === 'all'")
    assert await page.evaluate("window.iconInitCount") == 1
    assert not errors


@pytest.mark.parametrize("failure", ["rejected", "throw"])
async def test_service_worker_failure_keeps_hot_usable_without_uncaught_error(loading_browser, failure):
    page, _state, errors = loading_browser
    await page.add_init_script("window.swFailure = " + json.dumps(failure))
    await page.goto("http://127.0.0.1/hot", wait_until="domcontentloaded", timeout=3000)
    await page.locator("[data-hot-draft-text]").fill("Ручной текст")
    await page.locator("[data-hot-copy]").click()
    assert await page.evaluate("window.copiedText") == "Ручной текст"
    assert await page.evaluate("window.swRegistrations.length") == 1
    assert not errors


async def test_older_telegram_applies_supported_background_without_custom_header(loading_browser):
    page, state, errors = loading_browser
    await page.goto("http://127.0.0.1/hot", wait_until="domcontentloaded", timeout=3000)
    state["telegram_body"] = """window.telegramCalls = [];
    window.Telegram = {WebApp: {
      initData: 'test-telegram-payload',
      isVersionAtLeast: version => Number(version) <= 6.1,
      ready: () => window.telegramCalls.push('ready'),
      expand: () => window.telegramCalls.push('expand'),
      setHeaderColor: () => window.telegramCalls.push('unsupported-header'),
      setBackgroundColor: () => window.telegramCalls.push('background'),
      disableVerticalSwipes: () => window.telegramCalls.push('unsupported-swipes')
    }};"""
    state["telegram_release"].set()
    await page.wait_for_function("document.documentElement.classList.contains('inside-telegram')")
    assert await page.evaluate("window.telegramCalls") == ["ready", "expand", "background"]
    assert not errors
