"""E2E тесты с Playwright: критические пользовательские сценарии.

Запуск: pytest tests/test_e2e_playwright.py -v
Требует: playwright install chromium (выполняется один раз при настройке)
"""

from __future__ import annotations

import pytest
from playwright.async_api import async_playwright


@pytest.fixture(scope="session")
async def browser():
    """Session-scoped browser fixture."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        yield browser
        await browser.close()


@pytest.fixture
async def page(browser):
    """Page fixture that creates a new context and page for each test."""
    context = await browser.new_context()
    page = await context.new_page()
    credentials = {"email": "e2e@example.com", "password": "e2e-password-123"}
    response = await page.request.post(
        f"{BASE_URL}/auth/register",
        data={**credentials, "password_confirm": credentials["password"]},
        max_redirects=0,
    )
    if response.status not in (302, 303):
        await page.request.post(f"{BASE_URL}/auth/login", data=credentials, max_redirects=0)
    yield page
    await context.close()


# Base URL for the application (adjust for your test environment)
BASE_URL = "http://127.0.0.1:8000"


@pytest.mark.e2e
async def test_homepage_loads(page):
    """Главная страница загружается и содержит основные элементы."""
    await page.goto(BASE_URL)
    await page.wait_for_load_state("networkidle")

    # Проверяем заголовок
    await page.wait_for_selector("h1", timeout=5000)
    h1_text = await page.locator("h1").first.text_content()
    assert "Сайт открывается" in h1_text

    # Проверяем CTA: форма в герое и ссылка на объяснение
    cta_primary = page.locator('button:has-text("Проверить сайт")')
    cta_secondary = page.locator('a:has-text("Как это работает")')
    await cta_primary.wait_for(state="visible", timeout=5000)
    await cta_secondary.wait_for(state="visible", timeout=5000)

    # Проверяем trust badge
    trust_badge = page.locator("text=Бесплатно · без установки")
    await trust_badge.wait_for(state="visible", timeout=5000)


@pytest.mark.e2e
async def test_landing_cta_redirects_to_scan(page):
    """Клик по CTA на странице возможностей ведёт на быструю проверку."""
    await page.goto(f"{BASE_URL}/landing")
    await page.wait_for_load_state("networkidle")

    cta = page.locator('a:has-text("Проверить сайт")').first
    await cta.click()
    await page.wait_for_load_state("networkidle")

    assert "/scan" in page.url
    await page.wait_for_selector("h1:has-text('Быстрая проверка')", timeout=5000)


@pytest.mark.e2e
async def test_how_it_works_scroll(page):
    """Клик по 'Как это работает' прокручивает к секции."""
    await page.goto(BASE_URL)
    await page.wait_for_load_state("networkidle")

    cta = page.locator('a:has-text("Как это работает")').first
    await cta.click()
    await page.wait_for_load_state("networkidle")

    # Должен быть якорь #how-it-works на главной
    assert "#how-it-works" in page.url


@pytest.mark.e2e
async def test_landing_page_loads(page):
    """Страница «Возможности» загружается с ключевыми секциями."""
    await page.goto(f"{BASE_URL}/landing")
    await page.wait_for_load_state("networkidle")

    await page.wait_for_selector("h1", timeout=5000)
    h1_text = await page.locator("h1").first.text_content()
    assert "Возможности" in h1_text

    # Проверяем ключевые секции
    await page.wait_for_selector("#checks", timeout=5000)
    await page.wait_for_selector("#pipeline", timeout=5000)
    await page.wait_for_selector("#watchdog", timeout=5000)


@pytest.mark.e2e
async def test_oneshot_form_submission(page):
    """Форма разовой проверки отправляется корректно."""
    await page.goto(f"{BASE_URL}/scan/oneshot")
    await page.wait_for_load_state("networkidle")

    # Заполняем форму
    await page.fill('input[name="url"]', "https://example.com")
    await page.wait_for_selector('select[name="organization_id"]')
    await page.select_option('select[name="organization_id"]', index=0)

    # Отправляем форму
    await page.click('button[type="submit"]')
    await page.wait_for_load_state("networkidle")

    # Должно появиться сообщение о запуске или перенаправление
    await page.wait_for_selector("text=Проверка запущена", timeout=10000)


@pytest.mark.e2e
async def test_settings_page_toggles(page):
    """Настройки сайта: переключатели авторизации и Watchdog."""
    # Создаем сайт через API
    import tempfile

    from fastapi.testclient import TestClient

    from webscope.webapp.app import create_app

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    app = create_app(db_path=db_path)
    client = TestClient(app)

    # Создаем организацию и сайт
    org_resp = client.post("/api/organizations", json={"name": "E2E Test Org", "owner_email": "test@e2e.com"})
    org_id = org_resp.json()["id"]

    site_resp = client.post(
        "/api/sites",
        json={
            "url": "https://e2e-test.example.com",
            "organization_id": org_id,
            "schedule": "off",
        },
    )
    site_id = site_resp.json()["id"]

    # Логинимся через сессию (если есть auth)
    # Переходим на страницу настроек
    await page.goto(f"{BASE_URL}/sites/{site_id}/settings")
    await page.wait_for_load_state("networkidle")

    # Проверяем переключатель авторизации
    auth_toggle = page.locator("#auth-enabled")
    await auth_toggle.wait_for(state="visible", timeout=5000)
    is_checked = await auth_toggle.is_checked()

    if not is_checked:
        await auth_toggle.check()
        await page.wait_for_selector("#auth-block:not([hidden])", timeout=5000)

    # Проверяем переключатель Watchdog
    watchdog_toggle = page.locator("#watchdog-enabled")
    await watchdog_toggle.wait_for(state="visible", timeout=5000)

    if not await watchdog_toggle.is_checked():
        await watchdog_toggle.check()
        await page.wait_for_selector("#webhook-secret-field:not([hidden])", timeout=5000)
        await page.wait_for_selector("#watchdog-status:not([hidden])", timeout=5000)

    # Сохраняем настройки
    await page.click('button[type="submit"]:has-text("Сохранить настройки Watchdog")')
    await page.wait_for_load_state("networkidle")


@pytest.mark.e2e
async def test_theme_toggle(page):
    """Переключатель темы работает корректно."""
    await page.goto(BASE_URL)
    await page.wait_for_load_state("networkidle")

    theme_toggle = page.locator("#theme-toggle")
    await theme_toggle.wait_for(state="visible", timeout=5000)

    # Получаем начальную тему
    html = page.locator("html")
    initial_theme = await html.get_attribute("data-theme")

    # Кликаем переключатель
    await theme_toggle.click()
    await page.wait_for_timeout(300)

    # Проверяем, что тема изменилась
    new_theme = await html.get_attribute("data-theme")
    assert new_theme != initial_theme


@pytest.mark.e2e
async def test_mobile_menu(page):
    """Мобильное меню открывается и закрывается."""
    await page.goto(BASE_URL)
    await page.wait_for_load_state("networkidle")

    # Устанавливаем мобильный viewport
    await page.set_viewport_size({"width": 375, "height": 667})
    await page.wait_for_timeout(200)

    # Открываем меню
    menu_toggle = page.locator("#mobile-menu-toggle")
    await menu_toggle.wait_for(state="visible", timeout=5000)
    await menu_toggle.click()
    await page.wait_for_timeout(200)

    # Проверяем, что меню открылось
    mobile_nav = page.locator("#mobile-nav")
    await mobile_nav.wait_for(state="visible", timeout=5000)

    # Кликаем по ссылке - меню должно закрыться
    await mobile_nav.locator('a:has-text("Главная")').click()
    await page.wait_for_timeout(200)

    # Меню должно закрыться
    await mobile_nav.wait_for(state="hidden", timeout=5000)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "e2e"])
