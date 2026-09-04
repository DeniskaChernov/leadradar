"""Browser E2E: менеджерский funnel через Chromium (Playwright)."""

from __future__ import annotations

import pytest
from playwright.async_api import async_playwright

from tests.test_lead_workflow import create_lead


@pytest.mark.asyncio
async def test_leads_funnel_browser_take_contact_not_lead_reopen(session_factory, e2e_base_url):
    lead_id = await create_lead(session_factory, comment_id="browser-e2e-1", user_id="browser_user")

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            await page.goto(f"{e2e_base_url}/leads", wait_until="networkidle")
            assert await page.locator("[data-kanban-board]").count() == 1

            await page.goto(f"{e2e_base_url}/leads/{lead_id}", wait_until="networkidle")
            assert await page.locator(".stage-actions").count() == 1

            take_btn = page.locator(f'[data-lead-action="take"][data-lead-id="{lead_id}"]')
            await take_btn.click()
            # reloadSoon после take убирает кнопку take — ждём стабильную TAKEN-страницу.
            await take_btn.wait_for(state="detached", timeout=15_000)
            contacted_btn = page.locator(f'[data-stage="CONTACTED"][data-lead-id="{lead_id}"]')
            await contacted_btn.wait_for(state="visible", timeout=15_000)

            await contacted_btn.click()
            # После CONTACTED кнопка стадии пропадает — иначе confirm ломает отложенный reload.
            await contacted_btn.wait_for(state="detached", timeout=15_000)
            not_lead_btn = page.locator(f'[data-lead-action="not-lead"][data-lead-id="{lead_id}"]')
            await not_lead_btn.wait_for(state="visible", timeout=15_000)

            await not_lead_btn.click()
            confirm_ok = page.locator("#confirm.is-open [data-confirm-ok]")
            await confirm_ok.wait_for(state="visible", timeout=10_000)
            await confirm_ok.click()

            reopen_btn = page.locator(f'[data-lead-action="reopen"][data-lead-id="{lead_id}"]')
            await reopen_btn.wait_for(state="visible", timeout=20_000)
            await reopen_btn.click()
            await reopen_btn.wait_for(state="detached", timeout=15_000)
            # reopen_not_lead → TAKEN → снова стадия CONTACTED.
            await page.locator(
                f'[data-stage="CONTACTED"][data-lead-id="{lead_id}"]'
            ).wait_for(state="visible", timeout=15_000)
        finally:
            await browser.close()
