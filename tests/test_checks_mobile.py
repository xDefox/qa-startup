"""Тесты мобильных проверок (модуль checks/mobile.py) в реальном браузере.

Требуют Chromium. Если браузера нет — тесты пропускаются, а не падают.
"""

from __future__ import annotations

import pytest

from webscope.checks import mobile
from webscope.checks.js import JS_UTILS
from webscope.context import ScanContext
from webscope.models import Severity

playwright_api = pytest.importorskip("playwright.sync_api")

from webscope.scanner import _launch_chromium

pytestmark = pytest.mark.browser

# Правильный viewport и кнопки над 24×24 px — страница без находок.
GOOD_MOBILE_HTML = """
<html lang="ru"><head><title>Мобильная страница</title>
<meta name="viewport" content="width=device-width, initial-scale=1"></head>
<body>
  <a href="/catalog" id="cat" style="display:block;width:40px;height:40px">Каталог</a>
  <button id="go" style="width:60px;height:60px">Вперёд</button>
</body></html>
"""

# Мелкая ссылка (20×20) против хорошей кнопки (40×30) — ловит одну цель.
SMALL_TARGETS_HTML = """
<html lang="ru"><head><title>Мелкие цели</title>
<meta name="viewport" content="width=device-width, initial-scale=1"></head>
<body>
  <a href="/menu" id="menu" style="display:inline-block;width:20px;height:20px"></a>
  <button id="ok" style="width:40px;height:30px">Хорошая</button>
</body></html>
"""

# Формат viewport неправильный: width=320 без device-width.
BAD_VIEWPORT_HTML = """
<html lang="ru"><head><title>Формат viewport</title>
<meta name="viewport" content="width=320"></head>
<body><button id="b" style="width:40px;height:40px">Кнопка</button></body></html>
"""

ZOOM_LOCKED_HTML = """
<html lang="ru"><head><title>Зум запрещён</title>
<meta name="viewport" content="width=device-width, initial-scale=1, user-scalable=no"></head>
<body><button id="b" style="width:40px;height:40px">Кнопка</button></body></html>
"""

# Скроллируемый блок: горизонтальный overflow есть, touch-action блокирует панирование.
HSCROLL_OK_HTML = """
<html lang="ru"><head><title>Хороший скролл</title>
<meta name="viewport" content="width=device-width, initial-scale=1"></head>
<body>
  <div id="hscroll" style="overflow-x: auto; width: 300px; height: 60px;">
    <div style="width: 800px; height: 60px; background: #eee;">широкая полоса</div>
  </div>
</body></html>
"""

HSCROLL_BLOCKED_HTML = """
<html lang="ru"><head><title>Сломанный скролл</title>
<meta name="viewport" content="width=device-width, initial-scale=1"></head>
<body>
  <div id="hscroll" style="overflow-x: auto; width: 300px; height: 60px; touch-action: pan-y;">
    <div style="width: 800px; height: 60px; background: #eee;">широкая полоса</div>
  </div>
</body></html>
"""

DOC_BLOCKED_HTML = """
<html lang="ru"><head><title>Скролл документа заблокирован</title>
<meta name="viewport" content="width=device-width, initial-scale=1"></head>
<body style="touch-action: none; width: 2000px;"><div style="height: 50px;">широко</div></body></html>
"""

WIDE_HTML = """
<html lang="ru"><head><title>Широкий</title>
<meta name="viewport" content="width=device-width, initial-scale=1"></head>
<body><div style="width: 2000px; height: 50px; background: #ccc;">широкий блок</div></body></html>
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


def test_mobile_ok_page_is_clean(browser) -> None:
    context, ctx = _context(GOOD_MOBILE_HTML, browser)
    try:
        findings = mobile.run(context.pages[0], ctx)
    finally:
        context.close()

    assert findings == []


def test_mobile_flags_small_targets(browser) -> None:
    context, ctx = _context(SMALL_TARGETS_HTML, browser)
    try:
        findings = mobile.run(context.pages[0], ctx)
    finally:
        context.close()

    target_findings = [f for f in findings if f.rule == "viewport/target-size"]
    assert {f.selector for f in target_findings} == {"#menu"}, [f.selector for f in findings]
    target = target_findings[0]
    assert target.details["width"] == 20 and target.details["height"] == 20


def test_mobile_flags_bad_viewport_format(browser) -> None:
    context, ctx = _context(BAD_VIEWPORT_HTML, browser)
    try:
        findings = mobile.run(context.pages[0], ctx)
    finally:
        context.close()

    assert "viewport/meta-viewport" in _rules(findings)
    finding = next(f for f in findings if f.rule == "viewport/meta-viewport")
    assert finding.severity == Severity.SERIOUS
    assert finding.details["reason"] == "width"


def test_mobile_flags_zooming_locked(browser) -> None:
    context, ctx = _context(ZOOM_LOCKED_HTML, browser)
    try:
        findings = mobile.run(context.pages[0], ctx)
    finally:
        context.close()

    finding = next((f for f in findings if f.rule == "viewport/meta-viewport"), None)
    assert finding is not None
    assert finding.details["reason"] == "user-scalable"
    assert finding.severity == Severity.MODERATE


def test_mobile_good_viewport_is_clean(browser) -> None:
    """width=device-width без user-scalable=no — рекомендованный формат, находки нет."""
    context, ctx = _context(GOOD_MOBILE_HTML, browser)
    try:
        findings = mobile.run(context.pages[0], ctx)
    finally:
        context.close()

    assert "viewport/meta-viewport" not in _rules(findings)


def test_mobile_horizontal_scroll_ok(browser) -> None:
    context, ctx = _context(HSCROLL_OK_HTML, browser)
    try:
        findings = mobile.run(context.pages[0], ctx)
    finally:
        context.close()

    assert "viewport/horizontal-scroll" not in _rules(findings)


def test_mobile_flags_broken_horizontal_scroll(browser) -> None:
    """touch-action: pan-y на скроллируемом блоке — горизонтальный скролл не работает.

    Правило информационное (MINOR): желание разработчика, не то, за что владелец платит.
    """
    context, ctx = _context(HSCROLL_BLOCKED_HTML, browser)
    try:
        findings = mobile.run(context.pages[0], ctx)
    finally:
        context.close()

    finding = next((f for f in findings if f.rule == "viewport/horizontal-scroll"), None)
    assert finding is not None
    assert finding.selector == "#hscroll"
    assert finding.severity is Severity.MINOR
    assert finding.details["scrollWidth"] == 800


def test_mobile_flags_document_blocked_scroll(browser) -> None:
    """touch-action: none на body + широкий документ — скролл документа заблокирован.

    Правило информационное (MINOR).
    """
    context, ctx = _context(DOC_BLOCKED_HTML, browser)
    try:
        findings = mobile.run(context.pages[0], ctx)
    finally:
        context.close()

    findings_hs = [f for f in findings if f.rule == "viewport/horizontal-scroll"]
    assert findings_hs
    assert all(f.severity is Severity.MINOR for f in findings_hs)


def test_mobile_module_does_not_duplicate_overflow_finding(browser) -> None:
    """Горизонтальный документ ловит viewport/horizontal-overflow (viewport.run), не mobile."""
    context, ctx = _context(WIDE_HTML, browser)
    try:
        findings = mobile.run(context.pages[0], ctx)
    finally:
        context.close()

    assert findings == []


def test_mobile_module_registered() -> None:
    from webscope.checks import ALL_CHECKS, DEFAULT_CHECKS, REGISTRY

    assert REGISTRY["mobile"] is mobile.run
    assert "mobile" in DEFAULT_CHECKS
    assert "mobile" in ALL_CHECKS
