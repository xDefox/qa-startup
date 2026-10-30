"""Ошибки в консоли и упавшие сетевые запросы.

Это самый «честный» сигнал о поломках: если фронтенд падает с TypeError — это
видно в консоли, но часто не видно ни в одном отчёте.

Но в консоль пишут и чужие виджеты: карты, счётчики, SDK рекламы. Их ошибки —
не дефект проверяемого сайта, поэтому находки с чужого домена помечаются
``details.owner != "site"`` и не считаются проблемами сайта в отчёте и балле.
"""

from __future__ import annotations

from ..context import ScanContext
from ..models import Finding, Severity
from ..origins import resource_owner

_MAX_PER_KIND = 10


def _owner(resource_url: str | None, page_url: str) -> str:
    return resource_owner(resource_url or "", page_url)


def run(page: object, ctx: ScanContext) -> list[Finding]:
    findings: list[Finding] = []
    url = ctx.final_url

    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    for message in ctx.console_messages:
        if message.get("type") == "error":
            errors.append(message)
        elif message.get("type") == "warning":
            warnings.append(message)

    for message in errors[:_MAX_PER_KIND]:
        text = message.get("text", "") or ""
        location_url = message.get("location_url") or ""
        owner = _owner(location_url, url)
        details: dict[str, object] = {"location": location_url or message.get("location", "") or ""}
        if location_url:
            details["location_url"] = location_url
        details["owner"] = owner
        findings.append(
            Finding(
                rule="console/error",
                severity=Severity.SERIOUS,
                title="Ошибка в консоли браузера",
                message=text[:800],
                url=url,
                source="webscope.console",
                details=details,
            )
        )

    for message in warnings[:_MAX_PER_KIND]:
        warning_url = message.get("location_url") or ""
        findings.append(
            Finding(
                rule="console/warning",
                severity=Severity.MINOR,
                title="Предупреждение в консоли",
                message=message.get("text", "")[:500],
                url=url,
                source="webscope.console",
                # Как и у ошибок: предупреждение из чужого SDK — не дефект сайта.
                # Без owner такие находки попадали в балл сайта.
                details={"owner": _owner(warning_url, url), "location": warning_url},
            )
        )

    for request in ctx.failed_requests[:_MAX_PER_KIND]:
        status = request.get("status")
        res_url = request.get("url", "") or ""
        method = request.get("method", "GET") or "GET"
        failure = request.get("failure")
        owner = _owner(res_url, url)
        if status is None:
            severity, title = Severity.MODERATE, "Сетевой запрос не завершился"
            msg = f"{method} {res_url}"
            if failure:
                msg = f"{method} {res_url} — {failure}"
        elif status >= 500:
            severity, title = Severity.SERIOUS, f"Серверная ошибка при загрузке ресурса (HTTP {status})"
            msg = f"{method} {res_url} (HTTP {status})"
        else:
            severity, title = Severity.MODERATE, f"Ресурс не загрузился (HTTP {status})"
            msg = f"{method} {res_url} (HTTP {status})"
        findings.append(
            Finding(
                rule="console/failed-request",
                severity=severity,
                title=title,
                message=msg,
                url=url,
                source="webscope.console",
                details={"status": status, "resource": res_url, "owner": owner},
            )
        )

    return findings
