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

# Страница с блокировками клика: настоящая, ложная (слой со сквозной ссылкой
# на ту же цель) и невидимый под непрозрачным слайдом.
BLOCKED_HTML = """
<html lang="ru"><head><title>Кликабельность</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  body { margin: 0; }
  a, button { display: inline-block; }
  #real { position: fixed; left: 40px; top: 40px; z-index: 1; }
  .real-blocker { position: fixed; left: 0; top: 0; width: 300px; height: 300px;
                  background: rgba(0,0,0,.55); z-index: 5; }
  .card { position: relative; width: 400px; height: 200px; margin-top: 300px; }
  .card > * { position: absolute; left: 0; top: 0; width: 400px; height: 200px; }
  .card #same-href { background: #eee; z-index: 1; padding-top: 80px; text-align: center; }
  .card .overlay { z-index: 3; }
  .card .overlay a { width: 400px; height: 200px; text-indent: -9999px; overflow: hidden; }
  .slide-wrap { position: relative; width: 400px; height: 200px; margin: 40px; }
  .slide-wrap > * { position: absolute; left: 0; top: 0; width: 400px; height: 200px; }
  .slide-wrap .over { background-image: url(/active-slide.jpg); z-index: 2; }
</style></head>
<body>
  <a id="real" href="#real">Настоящая блокировка</a>
  <div class="real-blocker"></div>

  <div class="card">
    <a id="same-href" href="#same">Открыть меню</a>
    <div class="overlay"><a href="#same">сквозная ссылка</a></div>
  </div>

  <div class="slide-wrap">
    <a id="hidden-slide" href="#hidden" style="background-image:url(/under.jpg)"></a>
    <div class="over"></div>
  </div>

  <div style="position: relative; width: 300px; height: 120px; margin-top: 40px;">
    <div class="tn-bg" style="position: absolute; inset: 0; z-index: 1;
         background-image: url(/photo.jpg);"></div>
    <a id="tilda-wrapper" class="tn-atom" href="#menu"
       style="position: absolute; inset: 0; z-index: 2; background: none;"></a>
  </div>
</body>
</html>
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

# Ссылки/кнопки с доступными именами из содержимого (alt, aria-label) —
# то, что на реальных сайтах давало сотни ложных срабатываний.
NAMED_HTML = """
<html lang="ru"><head><title>Именованные ссылки</title>
<meta name="viewport" content="width=device-width, initial-scale=1"></head>
<body>
  <a href="https://t.me/example"><img src="/tg.png" alt="Telegram"></a>
  <a href="https://wa.example"><span aria-label="WhatsApp"></span></a>
  <a href="#menu" role="button"><svg viewBox="0 0 24 24"><title>Меню</title><path d="M0 0"/></svg></a>
  <a href="#promo"><span style="display:none">Скрытое меню</span></a>
  <a href="#real"><span aria-hidden="true">65 000</span> руб.</a>
  <span id="lbl-id">Поиск</span>
  <a href="#search"><span aria-labelledby="lbl-id"></span></a>
  <a href="#empty"></a>
  <a href="#empty2"><span style="display:none">только скрытый текст</span></a>
</body></html>
"""


# Страница с пустыми интерактивами: сколько находок на один элемент.
DUPLICATE_HTML = """
<html lang="ru"><head><title>Дубли</title>
<meta name="viewport" content="width=device-width, initial-scale=1"></head>
<body>
  <a href="#empty"></a>
  <a href="#popup" role="button"></a>
  <button></button>
  <form action="/send">
    <a href="#in-form" role="button"></a>
    <button type="submit"></button>
    <input type="submit" value="">
  </form>
</body>
</html>
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
    assert "content/frame-title" in rules
    assert "content/missing-charset" in rules
    assert "content/missing-lang" not in rules


def test_interaction_flags_only_real_blockers(browser) -> None:
    """button-blocked: настоящая блокировка ловится, ложные — нет.

    Регресс-тест на три FP с varkacoffee.by: сквозная ссылка с тем же href
    внутри слоя, невидимый под непрозрачным слайдом элемент и клик мимо
    элемента, лежащего за краем экрана.
    """
    from webscope.checks import interaction

    context, ctx = _context(BLOCKED_HTML, browser)
    try:
        findings = interaction.run(context.pages[0], ctx)
    finally:
        context.close()

    selectors = [f.selector or "" for f in findings]
    # Настоящая блокировка (полупрозрачный оверлей) — должна найтись.
    assert any("#real" in s for s in selectors), f"не нашли настоящую блокировку: {selectors}"
    # Ложные срабатывания — не должны найтись.
    assert not any("#same-href" in s for s in selectors), f"FP: сквозная ссылка: {selectors}"
    assert not any("#hidden-slide" in s for s in selectors), f"FP: невидимый слайд: {selectors}"
    # Tilda: прозрачная интерактивная обёртка поверх фоновой картинки — клик
    # доезжает до ссылки, это не перекрытие (FP с varkacoffee.by).
    assert not any("#tilda-wrapper" in s for s in selectors), f"FP: прозрачная обёртка Tilda: {selectors}"


def test_content_accepts_names_from_content(browser) -> None:
    """Имя ссылки/кнопки может быть внутри: alt картинки, aria-label, svg title.

    Регресс-тест на FP: раньше accessibleName читал только text(el), и
    <a><img alt="Telegram"></a> считалась ссылкой без имени (524 FP на кофе).
    """
    context, ctx = _context(NAMED_HTML, browser)
    try:
        findings = content.run(context.pages[0], ctx)
    finally:
        context.close()

    empty_links = [f for f in findings if f.rule == "content/empty-link-name"]
    hrefs = {(f.details or {}).get("href") for f in empty_links}

    # Именованные из содержимого — не должны попадать в находки.
    for href in (
        "https://t.me/example",  # alt у img внутри
        "https://wa.example",  # aria-label у вложенного span
        "#menu",  # svg <title>
        "#real",  # видимый текст + aria-hidden у части
        "#search",  # aria-labelledby у вложенного span
    ):
        assert href not in hrefs, f"ссылка {href} ошибочно посчитана без имени"

    # Пустая ссылка и ссылки только со скрытым (display:none) текстом —
    # настоящие находки: скринридер такое имя не читает.
    assert hrefs == {"#promo", "#empty", "#empty2"}, hrefs


def test_one_defect_is_one_finding(browser) -> None:
    """Пустой элемент без имени даёт ровно одну находку, а не две-три.

    Регресс-тест на дубли с varkacoffee.by: <a role="button"> попадал и в
    empty-link-name, и в empty-button-name, и в submit-without-accessible-name
    (525 уникальных элементов давали 966 находок).
    """
    from webscope.checks import content, forms

    context, ctx = _context(DUPLICATE_HTML, browser)
    try:
        page = context.pages[0]
        name_findings = [
            f
            for f in content.run(page, ctx) + forms.run(page, ctx)
            if f.rule
            in {
                "content/empty-link-name",
                "content/empty-button-name",
                "forms/submit-without-accessible-name",
            }
        ]
    finally:
        context.close()

    # Каждый из шести пустых интерактивов — одна находка, без дублей по правилам.
    rules_by_selector = {}
    for f in name_findings:
        rules_by_selector.setdefault(f.selector, []).append(f.rule)

    assert len(name_findings) == 6, rules_by_selector
    assert all(len(rules) == 1 for rules in rules_by_selector.values()), rules_by_selector


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
