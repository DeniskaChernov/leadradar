import pytest
from playwright.async_api import async_playwright


@pytest.mark.parametrize("e2e_base_url", [True], indirect=True)
async def test_browser_login_opens_search_and_hot(e2e_base_url):
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            await page.goto(f"{e2e_base_url}/radar", wait_until="networkidle")
            await page.get_by_label("Пароль доступа").fill("incorrect-password")
            await page.get_by_role("button", name="Войти в Lead Radar").click()
            await page.get_by_text("Неверный пароль.", exact=True).wait_for()
            await page.get_by_label("Пароль доступа").fill("browser-test-password")
            await page.get_by_role("button", name="Войти в Lead Radar").click()
            await page.locator("[data-find-leads]").wait_for()
            await page.goto(f"{e2e_base_url}/hot", wait_until="networkidle")
            assert await page.locator("[data-password-login]").count() == 0
            assert "HOT" in await page.title()
        finally:
            await browser.close()
