"""Оркестратор сканирования: браузер, архетип, запуск проверок, сбор evidence."""

from __future__ import annotations

import ipaddress
import os
import socket
import time
from collections.abc import Sequence
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from .archetype import detect_archetype
from .checks import DEFAULT_CHECKS, REGISTRY
from .checks.js import JS_UTILS
from .context import ScanContext
from .models import Finding, ScanResult, sort_findings

# Системные Chromium-ы — фолбэк, если playwright install chromium не выполнен.
_CHROMIUM_CANDIDATES = (
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
)

DEFAULT_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 webscope/0.1"
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
            raise ScanError(f"Не удалось разрешить хост {host}: {exc}") from exc
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
_AXE_EQUIVALENTS = {
    "image-alt": "content/image-alt",
    "button-name": "content/empty-button-name",
    "link-name": "content/empty-link-name",
    "frame-title": "content/iframe-title",
    "heading-order": "content/heading-order",
    "duplicate-id": "content/duplicate-id",
    "html-has-lang": "content/missing-lang",
    "document-title": "content/missing-title",
    "label": "forms/control-without-label",
}


def _snippet_key(snippet: str | None) -> str:
    """Нормализованный ключ элемента: сравниваем начало HTML, а не селектор."""
    if not snippet:
        return ""
    return "".join(snippet.split())[:80].lower()


def _dedupe_findings(findings: list[Finding]) -> list[Finding]:
    """Убирает дубли: одна и та же проблема, найденная двумя источниками."""
    own: dict[str, set[str]] = {}
    for finding in findings:
        if finding.source == "webscope.a11y":
            continue
        own.setdefault(finding.rule, set()).add(_snippet_key(finding.snippet))

    result: list[Finding] = []
    for finding in findings:
        if finding.source == "webscope.a11y":
            equivalent = _AXE_EQUIVALENTS.get(finding.rule)
            if equivalent and _snippet_key(finding.snippet) in own.get(equivalent, set()):
                continue  # тот же элемент уже пойман нашим правилом
        result.append(finding)
    return result


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
) -> ScanResult:
    """Сканирует страницу и возвращает результат."""
    validate_target(url, allow_private=allow_private)

    selected = list(checks or DEFAULT_CHECKS)
    unknown = [name for name in selected if name not in REGISTRY]
    if unknown:
        raise ScanError(f"Неизвестные проверки: {', '.join(unknown)}. Доступны: {', '.join(sorted(REGISTRY))}")

    started = time.monotonic()
    findings: list[Finding] = []

    with sync_playwright() as playwright:
        browser = _launch_chromium(playwright, headless)
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=user_agent,
            ignore_https_errors=False,
        )
        page = context.new_page()

        console_messages: list[dict[str, str]] = []
        failed_requests: list[dict] = []

        def on_console(message) -> None:
            location = ""
            try:
                location = str(message.location)
            except Exception:  # noqa: BLE001
                location = ""
            console_messages.append({"type": message.type, "text": message.text, "location": location})

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
            response = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            if response is not None and response.status >= 400:
                raise ScanError(f"Целевая страница вернула HTTP {response.status}")
            try:
                page.wait_for_load_state("networkidle", timeout=min(5000, timeout_ms))
            except PlaywrightError:
                pass  # networkidle недостижим на SPA с long-poll — это не ошибка

            page.add_script_tag(content=JS_UTILS)

            archetype = _collect_archetype(page)
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
            )

            for name in selected:
                findings.extend(REGISTRY[name](page, ctx))

            if evidence_dir is not None:
                _capture_evidence(page, findings, ctx)

            duration_ms = int((time.monotonic() - started) * 1000)
            return ScanResult(
                url=url,
                final_url=page.url,
                title=page.title(),
                archetype=archetype,
                findings=sort_findings(_dedupe_findings(findings)),
                duration_ms=duration_ms,
                pages_scanned=1,
            )
        finally:
            context.close()
            browser.close()
