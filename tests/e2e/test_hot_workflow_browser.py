"""Manual HOT workflow through the real HTTP handlers and a disposable database."""

from playwright.async_api import async_playwright, expect
from sqlalchemy import select

from app.db.models import ContactEvent, Lead, LeadStatus
from tests.test_lead_workflow import create_lead


async def test_hot_manual_save_reload_and_sent_opens_next_client(
    file_session_factory, e2e_base_url,
):
    lead_id = await create_lead(file_session_factory, "hot-browser-1", "hot_browser_one")
    next_id = await create_lead(file_session_factory, "hot-browser-2", "hot_browser_two")
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 390, "height": 844})
        csp_errors = []
        page.on('console', lambda event: csp_errors.append(event.text)
                if event.type == 'error' and 'Content Security Policy' in event.text else None)
        await page.route("https://**/*", lambda route: route.abort())
        try:
            await page.goto(f"{e2e_base_url}/hot?lead_id={lead_id}", wait_until="domcontentloaded")
            draft = page.locator("[data-hot-draft-text]")
            await draft.fill("Здравствуйте! Могу помочь с выбором мебели.")
            save = page.locator("[data-hot-save]")
            await save.click()
            await expect(page.locator('[data-hot-draft-badge]')).to_have_text('Готов')
            await page.reload(wait_until="domcontentloaded")
            assert await draft.input_value() == "Здравствуйте! Могу помочь с выбором мебели."

            message = "Здравствуйте! Подберём комплект по вашему запросу."
            await draft.fill(message)
            await page.locator("[data-hot-sent]").click()
            await page.locator("#confirm.is-open [data-confirm-ok]").click()
            await page.wait_for_url(f"**/hot?vertical=FURNITURE&lead_id={next_id}")
            await expect(page.locator('[data-hot-queue-toggle]')).to_have_attribute('aria-expanded', 'false')
            await page.locator('[data-hot-queue-toggle]').click()
            await page.locator(f'[data-hot-lead-id="{next_id}"].is-active').wait_for()
            assert await page.locator(f'[data-hot-lead-id="{lead_id}"]').count() == 0
            assert "hot_browser_two" in await page.locator("[data-hot-detail] h2").inner_text()
            assert not csp_errors
        finally:
            await browser.close()

    async with file_session_factory() as session:
        stored = await session.get(Lead, lead_id)
        assert stored.status == LeadStatus.OFFER_SENT
        assert stored.analysis_details["hot_outreach"]["message"] == message
        assert stored.analysis_details["hot_outreach"]["sent_at"]
        assert (await session.get(Lead, next_id)).status == LeadStatus.NEW
        events = list(await session.scalars(
            select(ContactEvent).where(ContactEvent.lead_id == lead_id)
        ))
        assert sum((event.payload_json or {}).get("kind") == "hot_outreach_sent"
                   for event in events) == 1
