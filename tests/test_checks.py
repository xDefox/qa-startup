"""Тесты проверок в реальном браузере.

Требуют Chromium. Если браузера нет — тесты пропускаются, а не падают.
"""

from __future__ import annotations

import pytest

from webscope.checks import content, forms, viewport
from webscope.checks.js import JS_UTILS
from webscope.context import ScanContext

playwright_api = pytest.importorskip("playwright.sync_api")

from webscope.scanner import _launch_chromium

pytestmark = pytest.mark.browser

BROKEN_HTML = """
<html lang="ru">
<head>
  <title>Тестовая страница</title>
  <meta name="description" content="описание">
  <meta name="viewport" content="width=device-width, initial-scale=1">
</head>
<body>
  <h1>Заголовок</h1>
  <h3>Пропущен уровень заголовка</h3>
  <img src="/logo.png">
  <a href="#"></a>
  <button></button>
  <div id="dup">a</div>
  <div id="dup">b</div>
  <input type="text" name="q" placeholder="Поиск по сайту">
  <iframe src="/frame"></iframe>
</body>
</html>
"""

WIDE_HTML = """
<html lang="ru"><head><title>Широкий</title>
<meta name="viewport" content="width=device-width, initial-scale=1"></head>
<body><div style="width: 2000px; height: 50px; background: #ccc;">широкий блок</div></body></html>
"""

# Страница без og-тегов: при репосте карточка будет пустой.
NO_OG_HTML = """
<html lang="ru"><head><title>Без соцкарточки</title>
<meta name="description" content="описание">
<meta name="viewport" content="width=device-width, initial-scale=1"></head>
<body><h1>Заголовок</h1></body></html>
"""

# Страница с корректной соцкарточкой.
FULL_OG_HTML = """
<html lang="ru"><head><title>Соцкарточка</title>
<meta name="description" content="описание">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta property="og:title" content="Заголовок для репоста">
<meta property="og:image" content="https://example.com/cover.png"></head>
<body><h1>Заголовок</h1></body></html>
"""


@pytest.fixture(scope="module")
def browser():
    try:
        with playwright_api.sync_playwright() as playwright:
            instance = _launch_chromium(playwright, headless=True)
            yield instance
            instance.close()
    except Exception as exc:  # noqa: BLE001 - нет браузера — пропускаем тесты
        pytest.skip(f"Chromium недоступен: {exc}")


def _context(html: str, browser) -> tuple[object, ScanContext]:
    context = browser.new_context(viewport={"width": 1280, "height": 800})
    page = context.new_page()
    page.set_content(html)
    page.add_script_tag(content=JS_UTILS)
    ctx = ScanContext(url="https://example.com/", final_url="https://example.com/", title="Тест")
    return context, ctx


def _rules(findings) -> set[str]:
    return {finding.rule for finding in findings}


def test_content_findings(browser) -> None:
    context, ctx = _context(BROKEN_HTML, browser)
    try:
        rules = _rules(content.run(context.pages[0], ctx))
    finally:
        context.close()

    assert "content/image-alt" in rules
    assert "content/heading-order" in rules
    assert "content/empty-link-name" in rules
    assert "content/empty-button-name" in rules
    assert "content/duplicate-id" in rules
    assert "content/iframe-title" in rules
    assert "content/missing-charset" in rules
    assert "content/missing-lang" not in rules


def test_forms_findings(browser) -> None:
    context, ctx = _context(BROKEN_HTML, browser)
    try:
        rules = _rules(forms.run(context.pages[0], ctx))
    finally:
        context.close()

    assert "forms/placeholder-as-label" in rules
    assert "forms/control-without-name" not in rules


def test_viewport_detects_overflow(browser) -> None:
    context, ctx = _context(WIDE_HTML, browser)
    try:
        findings = viewport.run(context.pages[0], ctx)
    finally:
        context.close()

    rules = _rules(findings)
    assert "viewport/horizontal-overflow" in rules
    overflow = next(f for f in findings if f.rule == "viewport/horizontal-overflow")
    assert overflow.severity.value == "serious"


def test_content_flags_missing_social_card(browser) -> None:
    context, ctx = _context(NO_OG_HTML, browser)
    try:
        findings = content.run(context.pages[0], ctx)
    finally:
        context.close()

    rules = _rules(findings)
    assert "content/missing-og-title" in rules
    assert "content/missing-og-image" in rules


def test_content_accepts_full_social_card(browser) -> None:
    context, ctx = _context(FULL_OG_HTML, browser)
    try:
        findings = content.run(context.pages[0], ctx)
    finally:
        context.close()

    rules = _rules(findings)
    assert "content/missing-og-title" not in rules
    assert "content/missing-og-image" not in rules


def test_checks_are_deterministic(browser) -> None:
    """Дважды одна и та же страница → бинарно идентичные находки и балл.

    Защищает центральное обещание продукта: повторный скан не выдумывает
    новых проблем и не теряет старые, иначе история и алерты бессмысленны.
    """
    context, ctx = _context(BROKEN_HTML, browser)
    try:
        page = context.pages[0]
        first = content.run(page, ctx)
        second = content.run(page, ctx)
    finally:
        context.close()

    assert [f.to_dict() for f in first] == [f.to_dict() for f in second]
