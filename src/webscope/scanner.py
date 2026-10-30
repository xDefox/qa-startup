"""Оркестратор сканирования: браузер, архетип, запуск проверок, сбор evidence."""

from __future__ import annotations

import base64
import ipaddress
import os
import socket
import time
from collections.abc import Sequence
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from . import __version__
from .archetype import detect_archetype
from .checks import DEFAULT_CHECKS, REGISTRY
from .checks.js import JS_UTILS
from .context import ScanContext
from .crawler import CrawlResult, PageTarget, crawl, representative_pages, squash_ws
from .diagnostics import diagnose_http_error, diagnose_navigation_error
from .models import AuthCredentials, Finding, ScanResult, Severity, sort_findings
from .pages import page_notes

# Системные Chromium-ы — фолбэк, если playwright install chromium не выполнен.
_CHROMIUM_CANDIDATES = (
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
)

DEFAULT_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    f" webscope/{__version__}"
)


class ScanError(RuntimeError):
    """Ошибка, из-за которой сканирование невозможно."""


def validate_target(url: str, allow_private: bool = False) -> str:
    """Проверяет, что цель сканирования безопасна.

    Защита от SSRF: только http/https, без credentials в URL, без локальных и
    приватных адресов (если явно не разрешено через ``allow_private`` или
    переменную окружения ``WEBSCOPE_ALLOW_PRIVATE=1``).
    """
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ScanError(f"Недопустимая схема: {parsed.scheme or '(пусто)'} — поддерживаются только http и https")
    if parsed.username or parsed.password:
        raise ScanError("Логин и пароль в URL не поддерживаются — используйте заголовки или cookies")
    host = parsed.hostname
    if not host:
        raise ScanError("В URL нет хоста")

    if not allow_private and os.environ.get("WEBSCOPE_ALLOW_PRIVATE") != "1":
        try:
            infos = socket.getaddrinfo(host, None)
        except socket.gaierror as exc:
            raise ScanError(
                f"Не удалось открыть {url}: домен не найден. "
                "Проверьте адрес на опечатку; возможно, DNS-запись ещё не создана."
            ) from exc
        for info in infos:
            address = ipaddress.ip_address(info[4][0])
            if (
                address.is_private
                or address.is_loopback
                or address.is_link_local
                or address.is_reserved
                or address.is_multicast
                or address.is_unspecified
            ):
                raise ScanError(f"Хост {host} резолвится в непубличный адрес {address} — сканирование заблокировано")

    return url


def _launch_chromium(playwright, headless: bool):
    try:
        return playwright.chromium.launch(headless=headless)
    except PlaywrightError:
        for candidate in _CHROMIUM_CANDIDATES:
            if Path(candidate).exists():
                return playwright.chromium.launch(headless=headless, executable_path=candidate)
        raise


# --- авторизация на защищенных сайтах ---

_PASSWORD_INPUT = 'input[type="password"]:visible'
_USERNAME_INPUT = (
    'input[type="text"]:visible, input[type="email"]:visible, input[type="tel"]:visible, '
    'input[autocomplete="username"]:visible, input[name*="user" i]:visible, '
    'input[name*="login" i]:visible'
)


def _basic_auth_headers(auth: AuthCredentials | None) -> dict[str, str] | None:
    """Заголовок ``Authorization: Basic`` для каждого запроса (или None)."""
    if auth is None or auth.kind != "basic":
        return None
    token = base64.b64encode(f"{auth.login}:{auth.password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def _form_login(page, auth: AuthCredentials, *, start_url: str, timeout_ms: int) -> None:
    """Входит через форму логина и ждёт, пока поле пароля исчезнет.

    Эвристика, а не адаптер конкретной CMS: на странице ищем видимое поле
    пароля, рядом — поле логина, отправляем ближайшую форму (кнопка submit
    или Enter). Успех — поле пароля исчезло: редирект после входа или SPA
    спрятала форма. Неудача — поле осталось: кидаем ScanError с понятным
    текстом, он попадает в отчёт прогона.
    """
    target = (auth.login_url or "").strip() or start_url
    try:
        response = page.goto(target, wait_until="domcontentloaded", timeout=timeout_ms)
    except PlaywrightError as exc:
        raise ScanError(diagnose_navigation_error(target, exc, timeout_ms=timeout_ms)) from exc
    if response is not None and response.status >= 400:
        raise ScanError(diagnose_http_error(target, response.status))

    passwords = page.locator(_PASSWORD_INPUT)
    if passwords.count() == 0:
        raise ScanError(
            f"Не удалось войти: на {target} нет формы входа — укажите адрес страницы входа в настройках авторизации."
        )
    password_input = passwords.first

    # Поля и кнопка — внутри формы с паролем; без <form> работаем на уровне страницы.
    scope = page
    forms = password_input.locator("xpath=ancestor::form")
    if forms.count() > 0:
        scope = forms.first
    users = scope.locator(_USERNAME_INPUT)
    if users.count() > 0:
        users.first.fill(auth.login)
    password_input.fill(auth.password)

    buttons = scope.locator('button[type="submit"], input[type="submit"], button')
    try:
        if buttons.count() > 0:
            buttons.first.click()
        else:
            password_input.press("Enter")
    except PlaywrightError as exc:
        raise ScanError(f"Не удалось войти: не смогли отправить форму на {target} ({exc}).") from exc

    # Ждём успеха: поле пароля исчезло. Если оно осталось — вход не принят.
    deadline = time.monotonic() + min(10.0, max(3.0, timeout_ms / 1000))
    while time.monotonic() < deadline:
        try:
            if page.locator(_PASSWORD_INPUT).count() == 0:
                return
        except PlaywrightError:
            pass  # страница перезагружается — проверим ещё раз
        page.wait_for_timeout(250)
    raise ScanError(
        f"Не удалось войти на {target}: после отправки формы страница входа осталась — проверьте логин и пароль."
    )


def _form_login_cookies(
    root_url: str,
    auth: AuthCredentials,
    *,
    headless: bool,
    user_agent: str,
    timeout_ms: int,
) -> list[dict]:
    """Входит через форму в отдельной сессии и возвращает её cookies.

    Cookies нужны краулеру (он ходит по сайту без браузера) и основному
    контексту сканирования — тот получит их через ``add_cookies``.
    """
    with sync_playwright() as playwright:
        browser = _launch_chromium(playwright, headless)
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=user_agent,
            ignore_https_errors=False,
        )
        try:
            page = context.new_page()
            _form_login(page, auth, start_url=root_url, timeout_ms=timeout_ms)
            return context.cookies()
        finally:
            context.close()
            browser.close()


def _collect_archetype(page) -> dict:
    probe = page.evaluate(  # type: ignore[attr-defined]
        r"""
        () => {
          const html = document.documentElement.outerHTML;
          const scriptSrcs = Array.from(document.querySelectorAll('script[src]')).map((s) => s.getAttribute('src') || '');
          const classNames = Array.from(document.querySelectorAll('[class]'))
            .slice(0, 800)
            .flatMap((el) => (el.getAttribute('class') || '').split(/\s+/))
            .filter(Boolean)
            .slice(0, 400);
          const generator = document.querySelector('meta[name="generator"]');
          const globals = ['__NEXT_DATA__', '__NUXT__', 'React', 'Vue', 'ng', '__remixContext'];
          return {
            html: html.slice(0, 200000),
            scriptSrcs,
            classNames,
            generator: generator ? (generator.getAttribute('content') || '') : '',
            globalsPresent: globals.filter((g) => typeof window[g] !== 'undefined'),
          };
        }
        """
    )
    return detect_archetype(
        html=probe.get("html", ""),
        script_srcs=probe.get("scriptSrcs", []),
        class_names=probe.get("classNames", []),
        meta_generator=probe.get("generator", ""),
        globals_present=probe.get("globalsPresent", []),
    )


def _capture_evidence(page, findings: list[Finding], ctx: ScanContext) -> None:
    """Сохраняет скриншот элемента для каждой находки с селектором."""
    if ctx.evidence_dir is None:
        return
    for index, finding in enumerate(findings):
        if not finding.selector:
            continue
        safe_rule = "".join(char if char.isalnum() or char in "-_" else "_" for char in finding.rule)
        path = ctx.evidence_path(f"{index:03d}_{safe_rule}.png")
        if path is None:
            continue
        try:
            page.locator(finding.selector).first.screenshot(path=str(path), timeout=5000)
            finding.details["evidence"] = path.name
        except (PlaywrightError, ValueError):
            # Скриншот — вспомогательный артефакт: его отсутствие не отменяет находку.
            continue


# Правила axe, которые дублируют наши собственные проверки. Для таких пар
# оставляем нашу находку: у неё понятное сообщение и критерий приёмки для агента.
# Значение — список: одна axe-права может закрываться разными нашими правилами
# (пустая кнопка ловится в контенте, а кнопка формы — в forms).
_AXE_EQUIVALENTS = {
    # Ссылка/картинка внутри ссылки: axe image-alt и link-name ловят тот же
    # дефект, что наш content/empty-link-name — один <a><img без alt></a> давал
    # три находки. Оставляем нашу (у неё понятная формулировка про ссылку).
    "image-alt": ["content/image-alt", "content/empty-link-name"],
    "button-name": ["content/empty-button-name", "forms/submit-without-accessible-name"],
    "link-name": ["content/empty-link-name"],
    # У axe правило называется frame-title, у нас — content/frame-title.
    # Опечатка (content/iframe-title) ломала дедуп: один iframe в отчёте дважды.
    "frame-title": ["content/frame-title"],
    "heading-order": ["content/heading-order"],
    "duplicate-id": ["content/duplicate-id"],
    "html-has-lang": ["content/missing-lang"],
    "document-title": ["content/missing-title"],
    "page-has-heading-one": ["content/no-h1"],
    "label": ["forms/control-without-label"],
}

# Правила уровня документа: на странице ровно один экземпляр, элемента нет,
# сниппет пуст. Для них дубль с axe сопоставляется по URL страницы.
_DOCUMENT_OWN_RULES = {"content/missing-lang", "content/missing-title", "content/no-h1"}


def _snippet_key(snippet: str | None) -> str:
    """Нормализованный ключ элемента: сравниваем начало HTML, а не селектор."""
    if not snippet:
        return ""
    return "".join(snippet.split())[:80].lower()


def _dedupe_findings(findings: list[Finding]) -> list[Finding]:
    """Убирает дубли: одна и та же проблема, найденная двумя источниками."""
    own: dict[str, set[str]] = {}
    # Документные проверки без сниппета (lang, title, h1) нельзя сопоставлять
    # по HTML — для них якорь страницы это сам URL.
    own_urls: dict[str, set[str]] = {}
    for finding in findings:
        if finding.source == "webscope.a11y":
            continue
        key = _snippet_key(finding.snippet)
        if key:
            own.setdefault(finding.rule, set()).add(key)
        elif finding.rule in _DOCUMENT_OWN_RULES:
            own_urls.setdefault(finding.rule, set()).add(finding.url or "")

    result: list[Finding] = []
    for finding in findings:
        if finding.source != "webscope.a11y":
            result.append(finding)
            continue
        # axe-находка — дубль, если наше правило уже поймало тот же элемент
        # (а для проверок уровня документа — ту же страницу).
        key = _snippet_key(finding.snippet)
        url = finding.url or ""
        duplicated = any(
            key in own.get(equivalent, set()) or url in own_urls.get(equivalent, set())
            for equivalent in _AXE_EQUIVALENTS.get(finding.rule, [])
        )
        if not duplicated:
            result.append(finding)
    return result


def _scan_page(
    page,
    url: str,
    *,
    checks: Sequence[str],
    timeout_ms: int,
    evidence_dir: Path | None,
    max_link_checks: int,
) -> tuple[list[Finding], ScanContext]:
    """Открывает страницу и прогоняет по ней проверки. Возвращает находки и контекст."""
    console_messages: list[dict[str, str]] = []
    failed_requests: list[dict] = []

    def on_console(message) -> None:
        # message.location — объект Playwright; str() от него даёт Python-repr
        # вида "{'url': ...}", поэтому URL берём из атрибута.
        location = getattr(message, "location", None) or {}
        location_url = location.get("url", "") if isinstance(location, dict) else ""
        console_messages.append(
            {"type": message.type, "text": message.text, "location": location_url, "location_url": location_url}
        )

    def on_request_failed(request) -> None:
        failure = getattr(request, "failure", None)
        failed_requests.append(
            {
                "url": request.url,
                "method": request.method,
                "status": None,
                "failure": getattr(failure, "error_text", None) or "request failed",
            }
        )

    def on_response(response) -> None:
        if response.status >= 400:
            failed_requests.append(
                {
                    "url": response.url,
                    "method": response.request.method,
                    "status": response.status,
                    "failure": None,
                }
            )

    page.on("console", on_console)
    page.on("requestfailed", on_request_failed)
    page.on("response", on_response)

    try:
        try:
            response = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        except PlaywrightError as exc:
            raise ScanError(diagnose_navigation_error(url, exc, timeout_ms=timeout_ms)) from exc
        if response is not None and response.status >= 400:
            raise ScanError(diagnose_http_error(url, response.status))
        try:
            page.wait_for_load_state("networkidle", timeout=min(5000, timeout_ms))
        except PlaywrightError:
            pass  # networkidle недостижим на SPA с long-poll — это не ошибка

        page.add_script_tag(content=JS_UTILS)

        archetype = _collect_archetype(page)
        notes: list[str] = page_notes(url, page.url)
        ctx = ScanContext(
            url=url,
            final_url=page.url,
            title=page.title(),
            archetype=archetype,
            console_messages=console_messages,
            failed_requests=failed_requests,
            evidence_dir=evidence_dir,
            timeout_ms=timeout_ms,
            max_link_checks=max_link_checks,
            notes=notes,
        )

        findings: list[Finding] = []
        for name in checks:
            findings.extend(REGISTRY[name](page, ctx))
        if evidence_dir is not None:
            _capture_evidence(page, findings, ctx)
        return findings, ctx
    finally:
        page.remove_listener("console", on_console)
        page.remove_listener("requestfailed", on_request_failed)
        page.remove_listener("response", on_response)


def _resolve_checks(checks: Sequence[str] | None) -> list[str]:
    selected = list(checks or DEFAULT_CHECKS)
    unknown = [name for name in selected if name not in REGISTRY]
    if unknown:
        raise ScanError(f"Неизвестные проверки: {', '.join(unknown)}. Доступны: {', '.join(sorted(REGISTRY))}")
    return selected


def _meta_key(value: str) -> str:
    """Нормализует title/description для сравнения: регистр и пробелы не важны."""
    return squash_ws(value).lower()


def _duplicate_meta_findings(crawl_result: CrawlResult) -> list[Finding]:
    """Ищет одинаковые title/description у страниц одного шаблона.

    Каталог из 200 товаров, у всех заголовок «Товар» — поиск и вкладки не
    различают страницы. Сравниваем только внутри шаблона: у главной и карточки
    разные шаблоны, их одинаковые заголовки — не проблема.
    """
    findings: list[Finding] = []
    for template, urls in sorted(crawl_result.templates.items()):
        pages = [page for page in crawl_result.pages if page.url in urls]
        for field_name, rule, severity in (
            ("title", "content/duplicate-title", Severity.MODERATE),
            ("description", "content/duplicate-description", Severity.MINOR),
        ):
            groups: dict[str, list[PageTarget]] = {}
            for page in pages:
                value = getattr(page, field_name, "") or ""
                if _meta_key(value):
                    groups.setdefault(_meta_key(value), []).append(page)
            for group in groups.values():
                if len(group) < 2:
                    continue
                sorted_group = sorted(group, key=lambda p: p.url)
                sample = sorted_group[0]
                display = getattr(sample, field_name, "").strip()
                findings.append(
                    Finding(
                        rule=rule,
                        severity=severity,
                        title=f"Одинаковый {field_name} у {len(group)} страниц шаблона",
                        message=(
                            f"Страницы одного шаблона ({template}) имеют одинаковый "
                            f"{field_name} «{display}» — поисковики и вкладки не различают их."
                        ),
                        url=sample.url,
                        source="webscope.crawler",
                        details={
                            "template": template,
                            "field": field_name,
                            "value": display,
                            "count": len(group),
                            "examples": [p.url for p in sorted_group[:5]],
                        },
                    )
                )
    return findings


def scan(
    url: str,
    *,
    checks: Sequence[str] | None = None,
    timeout_ms: int = 30_000,
    headless: bool = True,
    evidence_dir: Path | None = None,
    max_link_checks: int = 20,
    allow_private: bool = False,
    user_agent: str = DEFAULT_UA,
    auth: AuthCredentials | None = None,
) -> ScanResult:
    """Сканирует одну страницу и возвращает результат.

    ``auth`` — вход на защищённый сайт: ``basic`` шлёт заголовок на каждый
    запрос, ``form`` сначала входит через форму (сессия живёт в контексте).
    """
    validate_target(url, allow_private=allow_private)
    selected = _resolve_checks(checks)
    started = time.monotonic()

    with sync_playwright() as playwright:
        browser = _launch_chromium(playwright, headless)
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=user_agent,
            ignore_https_errors=False,
            extra_http_headers=_basic_auth_headers(auth),
        )
        page = context.new_page()
        try:
            if auth is not None and auth.kind == "form":
                _form_login(page, auth, start_url=url, timeout_ms=timeout_ms)
            findings, ctx = _scan_page(
                page,
                url,
                checks=selected,
                timeout_ms=timeout_ms,
                evidence_dir=evidence_dir,
                max_link_checks=max_link_checks,
            )
        finally:
            context.close()
            browser.close()

    duration_ms = int((time.monotonic() - started) * 1000)
    return ScanResult(
        url=url,
        final_url=ctx.final_url,
        title=ctx.title,
        archetype=ctx.archetype,
        findings=sort_findings(_dedupe_findings(findings)),
        duration_ms=duration_ms,
        pages_scanned=1,
    )


def scan_site(
    root_url: str,
    *,
    max_pages: int = 30,
    max_depth: int = 2,
    respect_robots: bool = True,
    all_pages: bool = False,
    checks: Sequence[str] | None = None,
    timeout_ms: int = 30_000,
    headless: bool = True,
    evidence_dir: Path | None = None,
    max_link_checks: int = 20,
    allow_private: bool = False,
    user_agent: str = DEFAULT_UA,
    auth: AuthCredentials | None = None,
) -> tuple[ScanResult, CrawlResult]:
    """Обходит сайт и сканирует по одной странице каждого шаблона.

    Возвращает (результат, результат обхода). Одна страница = один шаблон:
    300 страниц каталога проверяются по одному представителю.

    ``auth`` — вход на защищённый сайт. ``basic``: заголовок Authorization и
    краулеру, и браузеру. ``form``: до обходим заходим через форму в отдельной
    сессии и переносим её cookies в краулер и в контекст сканирования —
    обход и проверки идут уже «под пользователем».
    """
    validate_target(root_url, allow_private=allow_private)
    selected = _resolve_checks(checks)
    started = time.monotonic()

    auth_headers = _basic_auth_headers(auth)
    session_cookies: list[dict] | None = None
    if auth is not None and auth.kind == "form":
        session_cookies = _form_login_cookies(
            root_url,
            auth,
            headless=headless,
            user_agent=user_agent,
            timeout_ms=timeout_ms,
        )
    crawl_headers: dict[str, str] = dict(auth_headers or {})
    if session_cookies:
        crawl_headers["Cookie"] = "; ".join(f"{c['name']}={c['value']}" for c in session_cookies)

    crawl_result = crawl(
        root_url,
        max_pages=max_pages,
        max_depth=max_depth,
        respect_robots=respect_robots,
        user_agent=user_agent,
        headers=crawl_headers or None,
    )
    targets = representative_pages(crawl_result, all_pages=all_pages)

    findings: list[Finding] = []
    archetype: dict = {}
    title = ""
    final_url = root_url
    scanned = 0

    with sync_playwright() as playwright:
        browser = _launch_chromium(playwright, headless)
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=user_agent,
            ignore_https_errors=False,
            extra_http_headers=auth_headers,
        )
        if session_cookies:
            context.add_cookies(session_cookies)
        page = context.new_page()
        try:
            for target in targets:
                try:
                    page_findings, ctx = _scan_page(
                        page,
                        target.url,
                        checks=selected,
                        timeout_ms=timeout_ms,
                        evidence_dir=evidence_dir,
                        max_link_checks=max_link_checks,
                    )
                except ScanError as exc:
                    crawl_result.skipped.append({"url": target.url, "reason": str(exc)})
                    continue
                findings.extend(page_findings)
                scanned += 1
                if not archetype:
                    archetype = ctx.archetype
                    title = ctx.title
                    final_url = ctx.final_url
        finally:
            context.close()
            browser.close()

    # Ни одна страница не открылась (например, сервер отверг учётные данные) —
    # это ошибка прогона, а не отчёт с нулём проблем и оценкой 100.
    if scanned == 0:
        reason = crawl_result.skipped[-1]["reason"] if crawl_result.skipped else "причина неизвестна"
        raise ScanError(f"Не удалось открыть ни одной страницы — {reason}")

    duration_ms = int((time.monotonic() - started) * 1000)
    # Дубли title/description по шаблонам — проверка уровня сайта, а не страницы
    findings.extend(_duplicate_meta_findings(crawl_result))
    result = ScanResult(
        url=root_url,
        final_url=final_url,
        title=title,
        archetype=archetype,
        findings=sort_findings(_dedupe_findings(findings)),
        duration_ms=duration_ms,
        pages_scanned=scanned,
    )
    return result, crawl_result
