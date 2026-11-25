"""Ошибки JavaScript и упавшие ресурсы — только те, что реально ломают сайт.

Консоль — самый шумный источник: туда пишут чужие виджеты, браузерные
расширения, а сам Playwright иногда помечает все запросы как
``net::ERR_INVALID_ARGUMENT``. Поэтому находкой становится только то, что
подтверждено:

* необработанное исключение JavaScript на домене сайта;
* ресурс сайта, который действительно отвечает 4xx/5xx (при сомнении —
  повторная проверка обычным HTTP-запросом);
* ничего из чужих доменов, предупреждений и служебных сообщений браузера
  («Failed to load resource» дублирует сетевую проверку).
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

import httpx

from ..context import ScanContext
from ..models import Finding, Severity
from ..netguard import GuardedTransport
from ..origins import resource_owner

_MAX_PER_KIND = 10

# Сообщения, которые не являются дефектом сайта: артефакты браузера,
# блокировщиков, прокси и самого сканера.
_BENIGN_MESSAGES = (
    "resizeobserver loop",
    "script error.",
    "failed to load resource",
    "net::err_aborted",
    "net::err_blocked_by_client",
    "net::err_invalid_argument",
    "net::err_connection_closed",
)

# Ресурсы, падение которых не влияет на заявку и не проверяется.
_SKIP_RESOURCE_TYPES = {"websocket", "manifest", "ping", "beacon", "eventsource", "cspviolationreport"}
_SKIP_SUFFIXES = (".map",)
_DESTRUCTIVE_PATH = re.compile(r"/(logout|signout|log-out|delete|remove|unsubscribe)(/|$)", re.IGNORECASE)


def _owner(resource_url: str | None, page_url: str) -> str:
    return resource_owner(resource_url or "", page_url)


def _benign(text: str) -> bool:
    lowered = (text or "").strip().lower()
    return not lowered or any(marker in lowered for marker in _BENIGN_MESSAGES)


def _skip_resource(url: str, resource_type: str | None) -> bool:
    parsed = urlparse(url)
    path = (parsed.path or "").lower()
    if (resource_type or "") in _SKIP_RESOURCE_TYPES:
        return True
    if path.endswith(_SKIP_SUFFIXES) or path.endswith("/favicon.ico"):
        return True
    return _DESTRUCTIVE_PATH.search(path) is not None


def _verify_status(url: str, ctx: ScanContext) -> int | None:
    """Проверяет упавший ресурс обычным HTTP-запросом.

    ``requestfailed`` в Playwright срабатывает и на артефакты перехвата
    запросов: в проде все CSS/картинки получали ``net::ERR_INVALID_ARGUMENT``,
    хотя страница рисовалась. Повторный запрос отделяет реальную 404/500
    от ошибки сканера.
    """
    try:
        with (
            httpx.Client(
                timeout=httpx.Timeout(6.0, connect=3.0),
                follow_redirects=True,
                transport=GuardedTransport(allow_private=ctx.allow_private),
                headers=ctx.site_headers or None,
            ) as client,
            client.stream("GET", url) as response,
        ):
            return response.status_code
    except Exception:  # noqa: BLE001 - сеть не должна ронять проверку
        return None


def _resource_title(resource_type: str | None, status: int) -> str:
    kind = {
        "script": "скрипт",
        "stylesheet": "стили",
        "image": "изображение",
        "font": "шрифт",
        "document": "страница",
        "media": "видео/аудио",
    }.get(resource_type or "", "файл")
    if status >= 500:
        return f"Сервер не отдал {kind} сайта (HTTP {status})"
    return f"Не загрузился {kind} сайта (HTTP {status})"


def run(page: object, ctx: ScanContext) -> list[Finding]:
    findings: list[Finding] = []
    url = ctx.final_url

    # ── Необработанные ошибки JavaScript ──────────────────────────────────
    # ── Необработанные ошибки JavaScript и предупреждения на домене сайта ──────────────────
    seen_errors: set[tuple[str, str]] = set()
    for message in ctx.console_messages:
        msg_type = message.get("type")
        if msg_type not in {"error", "warning"}:
            continue
        text = (message.get("text") or "").strip()
        if _benign(text):
            continue
        location_url = message.get("location_url") or ""
        owner = _owner(location_url, url)
        # Ошибки от чужих SDK не считаем дефектом сайта.
        if msg_type == "error" and owner != "site":
            continue
        # Предупреждения показываем, даже если они из чужого SDK.
        if msg_type == "warning":
            rule = "console/warning"
            severity = Severity.MODERATE
        else:
            rule = "console/error"
            severity = Severity.SERIOUS
        key = (text[:400], location_url, msg_type)
        if key in seen_errors:
            continue
        seen_errors.add(key)
        findings.append(
            Finding(
                rule=rule,
                severity=severity,
                title="Предупреждение JavaScript" if msg_type == "warning" else "Ошибка JavaScript на странице",
                message=text[:800],
                url=url,
                source="webscope.console",
                details={
                    "kind": "js",
                    "location": location_url,
                    "owner": owner,
                },
            ),
        )
        if len(findings) >= _MAX_PER_KIND:
            break

    # ── Ресурсы сайта, которые не загрузились ─────────────────────────────
    # Один URL — одна находка: requestfailed и response могут рассказать
    # об одном и том же файле дважды.
    checked: set[str] = set()
    resource_findings = 0
    for request in ctx.failed_requests:
        if resource_findings >= _MAX_PER_KIND:
            break
        res_url = request.get("url", "") or ""
        if not res_url or res_url in checked:
            continue
        checked.add(res_url)

        method = (request.get("method") or "GET").upper()
        if method not in {"GET", "HEAD"}:
            continue

        resource_type = request.get("resource_type")
        if _skip_resource(res_url, resource_type):
            continue
        owner = _owner(res_url, url)
        if owner != "site":
            continue

        status = request.get("status")
        if status is None:
            # Таймауты и обрывы сети не называем дефектом сайта: сначала
            # перепроверяем. Если ресурс реально отдаётся — это был артефакт.
            status = _verify_status(res_url, ctx)
            if status is None or status < 400:
                continue

        if status in {401, 403} and (resource_type or "") in {"xhr", "fetch"}:
            # Закрытый API без сессии — ожидаемо, не повод чинить.
            continue
        if status == 429:
            # Лимит запросов — свойство сканера, а не поломка сайта.
            continue

        severity = Severity.SERIOUS if status >= 500 or resource_type in {"script", "stylesheet"} else Severity.MODERATE
        findings.append(
            Finding(
                rule="console/failed-request",
                severity=severity,
                title=_resource_title(resource_type, status),
                message=f"{method} {res_url} (HTTP {status})",
                url=url,
                source="webscope.console",
                details={
                    "kind": "resource",
                    "status": status,
                    "resource": res_url,
                    "resource_type": resource_type,
                    "owner": owner,
                },
            ),
        )
        resource_findings += 1

    return findings
