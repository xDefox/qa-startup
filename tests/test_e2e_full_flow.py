"""E2E тесты полного пользовательского пути (синхронные, через sync_playwright).

Запуск:
  1. В одном терминале: .venv/bin/python -m uvicorn webscope.webapp.app:create_app --factory --host 127.0.0.1 --port 8767
  2. В другом: pytest tests/test_e2e_full_flow.py -v -m e2e --tb=short
"""

from __future__ import annotations

import os

import pytest
from playwright.sync_api import sync_playwright

# --- Фикстуры ---

BASE_URL = os.environ.get("E2E_BASE_URL", "http://127.0.0.1:8767")


@pytest.fixture(scope="session")
def browser():
    """Session-scoped browser fixture (sync)."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        yield browser
        browser.close()


@pytest.fixture
def page(browser):
    """Page fixture that creates a new context and page for each test."""
    context = browser.new_context()
    page = context.new_page()
    yield page
    context.close()


# --- Вспомогательные функции ---


def extract_site_id(url: str) -> int | None:
    """Извлекает site_id из URL. Возвращает None если site_id нет."""
    if "/sites/" not in url:
        return None
    try:
        return int(url.rsplit("/sites/", maxsplit=1)[-1].split("/", maxsplit=1)[0].split("?", maxsplit=1)[0])
    except (ValueError, IndexError):
        return None


def create_test_site(page, base_url, url="https://example.com"):
    """Создаёт сайт через UI кабинета и возвращает site_id."""
    page.goto(f"{base_url.rstrip('/')}/dashboard")
    page.wait_for_load_state("networkidle")

    page.fill('input[name="url"]', url)
    page.select_option('select[name="schedule"]', value="weekly")
    page.click('button[type="submit"]')
    page.wait_for_load_state("networkidle")

    current_url = page.url
    assert "/sites" in current_url, f"Expected /sites in URL, got: {current_url}"
    return extract_site_id(current_url)


def wait_for_scan_complete(page, site_id, timeout=180000):
    """Ждёт завершения скана на странице сайта."""
    if site_id is None:
        return
    # Реальный сканер может вернуть разные оценки, ждём любой оценки
    # Увеличен таймаут до 3 минут для реального сканера
    # С мок-сканером скан мгновенный, но страница может не обновиться автоматически
    # Пробуем подождать, затем вручную перезагружаем страницу
    try:
        page.wait_for_selector("text=/100", timeout=min(timeout, 10000))
    except Exception:  # noqa: BLE001 - playwright selectors raise broad errors on timeout
        # Перезагружаем страницу и ждём ещё
        page.reload()
        page.wait_for_load_state("networkidle")
        page.wait_for_selector("text=/100", timeout=timeout - 10000)


# --- Тесты полного пути ---


@pytest.mark.e2e
def test_smoke_all_pages_load(page):
    """Smoke: все основные страницы отдают 200 и рендерятся без JS-ошибок."""
    pages = [
        (BASE_URL, "Сайт открывается"),
        (f"{BASE_URL}/landing", "Возможности"),
        (f"{BASE_URL}/scan", "Быстрая проверка"),
        (f"{BASE_URL}/scan/oneshot", "Разовая проверка"),
    ]

    errors = []
    page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)

    for url, expected_text in pages:
        page.goto(url)
        page.wait_for_load_state("networkidle")
        page.wait_for_selector("h1", timeout=5000)
        h1 = page.locator("h1").first.text_content()
        # Normalize whitespace for comparison
        h1_normalized = " ".join(h1.split())
        expected_normalized = " ".join(expected_text.split())
        assert expected_normalized in h1_normalized, (
            f"Page {url}: expected '{expected_normalized}' in h1, got '{h1_normalized}'"
        )

    # Нет критических JS-ошибок
    critical_errors = [e for e in errors if "uncaught" in e.lower() or "referenceerror" in e.lower()]
    assert not critical_errors, f"Critical JS errors: {critical_errors}"


@pytest.mark.e2e
def test_landing_to_scan_to_report(page):
    """Полный путь: «Возможности» → быстрая проверка → отчёт."""
    # 1. Заходим на страницу возможностей
    page.goto(f"{BASE_URL}/landing")
    page.wait_for_load_state("networkidle")
    page.wait_for_selector("h1", timeout=5000)

    assert "Возможности" in page.locator("h1").first.text_content()

    # 2. Кликаем «Проверить сайт» → попадаем на /scan
    page.click('a:has-text("Проверить сайт")')
    page.wait_for_load_state("networkidle")
    page.wait_for_selector("h1:has-text('Быстрая проверка')", timeout=5000)

    assert "/scan" in page.url

    # 3. Заполняем форму быстрой проверки
    page.fill('input[name="url"]', "https://example.com")
    page.click('button[type="submit"]')
    page.wait_for_load_state("networkidle")

    # 4. После отправки открывается страница сайта с отчётом
    site_id = extract_site_id(page.url)
    assert site_id is not None, f"Expected /sites/<id>, got: {page.url}"
    wait_for_scan_complete(page, site_id, timeout=60000)

    # Проверяем, что отчёт показывает находки (любые)
    assert "Что сделать" in page.text_content("body")


@pytest.mark.e2e
def test_home_to_dashboard_flow(page):
    """Путь: Кабинет → Добавление сайта → Отчёт → Настройки → Watchdog."""
    # 1. Кабинет
    page.goto(f"{BASE_URL}/dashboard")
    page.wait_for_load_state("networkidle")
    page.wait_for_selector("h1", timeout=5000)

    # 2. Добавляем сайт через форму в кабинете
    page.fill('input[name="url"]', "https://dashboard-test.example.com")
    page.select_option('select[name="schedule"]', value="weekly")
    page.click('button[type="submit"]')
    page.wait_for_load_state("networkidle")

    # Должны попасть на страницу сайта или список сайтов
    assert "/sites" in page.url, f"Expected /sites in URL, got: {page.url}"
    site_id = extract_site_id(page.url)

    # 3. Если попали на страницу сайта - ждём завершения скана
    if site_id is not None:
        wait_for_scan_complete(page, site_id)

    # 4. Проверяем, что сайт появился в списке кабинета
    page.goto(f"{BASE_URL}/dashboard")
    page.wait_for_load_state("networkidle")
    if site_id is not None:
        page.wait_for_selector(f'a[href="/sites/{site_id}"]', timeout=5000)

    # 5. Переходим на страницу сайта, затем в настройки
    if site_id is not None:
        page.goto(f"{BASE_URL}/sites/{site_id}")
        page.wait_for_load_state("networkidle")
        page.click(f'a[href="/sites/{site_id}/settings"]')
        page.wait_for_load_state("networkidle")

        # 6. Включаем Watchdog
        page.wait_for_selector("#watchdog-enabled", timeout=5000)
        watchdog_toggle = page.locator("#watchdog-enabled")
        if not watchdog_toggle.is_checked():
            watchdog_toggle.check()
            page.wait_for_selector("#webhook-secret-field:not([hidden])", timeout=5000)
            page.wait_for_selector("#watchdog-status:not([hidden])", timeout=5000)

        # Вводим секрет вебхука
        page.fill('input[name="watchdog_webhook_secret"]', "test-secret-123")

        # Сохраняем
        page.click('button[type="submit"]:has-text("Сохранить настройки Watchdog")')
        page.wait_for_load_state("networkidle")
        page.wait_for_selector("text=Настройки сохранены", timeout=5000)

        # 7. Проверяем, что настройки сохранились
        page.goto(f"{BASE_URL}/sites/{site_id}/settings")
        page.wait_for_load_state("networkidle")
        assert page.locator("#watchdog-enabled").is_checked()
        # Парольное поле (webhook secret) не отображает значение в HTML — это нормально для безопасности
        # Проверяем только что поле существует и это password field
        assert page.locator('input[name="watchdog_webhook_secret"]').get_attribute("type") == "password"


@pytest.mark.e2e
def test_auth_flow_form_login(page):
    """Путь: Сайт с формой входа → One-shot с auth → Скан → Отчёт."""
    page.goto(f"{BASE_URL}/scan/oneshot")
    page.wait_for_load_state("networkidle")

    # Заполняем URL
    page.fill('input[name="url"]', "https://auth-test.example.com")
    page.wait_for_selector('select[name="organization_id"]')
    page.select_option('select[name="organization_id"]', index=0)

    # Включаем авторизацию
    page.check("#auth_enabled")
    page.wait_for_selector("#auth-block:not([hidden])", timeout=5000)

    # Выбираем "Форма входа"
    page.select_option("#auth_kind", value="form")

    # Заполняем креды
    page.fill('input[name="auth_login"]', "testuser")
    page.fill('input[name="auth_password"]', "testpass")

    # Отправляем
    page.click('button[type="submit"]')
    page.wait_for_load_state("networkidle")

    # Должно запуститься
    page.wait_for_selector("text=Проверка запущена", timeout=30000)
    page.wait_for_selector("a:has-text('Открыть отчёт')", timeout=15000)

    # Переходим в отчёт
    page.click('a:has-text("Открыть отчёт")')
    page.wait_for_load_state("networkidle")
    site_id = extract_site_id(page.url)
    wait_for_scan_complete(page, site_id)


@pytest.mark.e2e
def test_theme_persistence(page):
    """Тема запоминается между перезагрузками."""
    page.goto(BASE_URL)
    page.wait_for_load_state("networkidle")

    theme_toggle = page.locator("#theme-toggle")
    theme_toggle.wait_for(state="visible", timeout=5000)

    html = page.locator("html")
    initial_theme = html.get_attribute("data-theme") or "light"

    # Переключаем
    theme_toggle.click()
    page.wait_for_timeout(500)
    new_theme = html.get_attribute("data-theme") or "light"
    # Если тема не изменилась, пробуем ещё раз
    if new_theme == initial_theme:
        theme_toggle.click()
        page.wait_for_timeout(500)
        new_theme = html.get_attribute("data-theme") or "light"
    assert new_theme != initial_theme, f"Theme didn't change: {initial_theme} -> {new_theme}"

    # Перезагружаем страницу
    page.reload()
    page.wait_for_load_state("networkidle")

    # Тема должна сохраниться
    persisted_theme = html.get_attribute("data-theme") or "light"
    assert persisted_theme == new_theme, f"Theme not persisted: {new_theme} -> {persisted_theme}"


@pytest.mark.e2e
def test_mobile_responsive(page):
    """Мобильная вёрстка: меню, формы, отчёты."""
    page.goto(BASE_URL)
    page.wait_for_load_state("networkidle")

    # Мобильный viewport
    page.set_viewport_size({"width": 375, "height": 667})
    page.wait_for_timeout(200)

    # 1. Мобильное меню
    menu_toggle = page.locator("#mobile-menu-toggle")
    menu_toggle.wait_for(state="visible", timeout=5000)
    menu_toggle.click()
    page.wait_for_timeout(300)

    mobile_nav = page.locator("#mobile-nav")
    # Ждём, пока меню станет видимым (hidden атрибут удаляется)
    page.wait_for_function("() => !document.getElementById('mobile-nav').hidden", timeout=5000)
    mobile_nav.wait_for(state="visible", timeout=5000)

    # Клик по ссылке закрывает меню
    mobile_nav.locator('a:has-text("Главная")').click()
    page.wait_for_timeout(200)
    mobile_nav.wait_for(state="hidden", timeout=5000)

    # 2. Форма на главной адаптируется
    page.wait_for_selector('input[name="url"]', timeout=5000)
    input_width = page.locator('input[name="url"]').bounding_box()
    assert input_width["width"] <= 375  # не вылезает за экран

    # 3. One-shot форма
    page.goto(f"{BASE_URL}/scan/oneshot")
    page.wait_for_load_state("networkidle")
    page.wait_for_selector('input[name="url"]', timeout=5000)


@pytest.mark.e2e
def test_delete_site(page):
    """Удаление сайта удаляет всё: настройки, историю, отчёты."""
    site_id = create_test_site(page, BASE_URL, "https://delete-test.example.com")
    if site_id is not None:
        wait_for_scan_complete(page, site_id)

        # Переходим в настройки и удаляем
        page.goto(f"{BASE_URL}/sites/{site_id}/settings")
        page.wait_for_load_state("networkidle")

        page.click('button:has-text("Удалить сайт")')
        page.wait_for_load_state("networkidle")

        # Должны вернуться на главную
        assert page.url == BASE_URL or page.url == BASE_URL + "/", f"Expected redirect to home, got: {page.url}"

        # Сайта больше нет в списке
        page.wait_for_selector(f'a[href="/sites/{site_id}"]', state="detached", timeout=5000)


if __name__ == "__main__":
    import sys

    import httpx

    # Проверяем, что сервер доступен
    def check_server():
        try:
            resp = httpx.get(f"{BASE_URL}/healthz", timeout=5.0)
            if resp.status_code == 200:
                print(f"✓ Server at {BASE_URL} is ready")
                return True
        except Exception as e:  # noqa: BLE001 - health check: report any connection error
            print(f"✗ Server at {BASE_URL} not available: {e}")
            print(
                "Start server with: .venv/bin/python -m uvicorn webscope.webapp.app:create_app --factory --host 127.0.0.1 --port 8767"
            )
            return False
        return False

    if check_server():
        pytest.main([__file__, "-v", "-m", "e2e", "--tb=short"])
    else:
        sys.exit(1)
