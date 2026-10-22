"""Ошибки в консоли и упавшие сетевые запросы.

Это самый «честный» сигнал о поломках: если фронтенд падает с TypeError — это
видно в консоли, но часто не видно ни в одном отчёте.
"""

from __future__ import annotations

from ..context import ScanContext
from ..models import Finding, Severity

_MAX_PER_KIND = 10


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
        loc = message.get("location", "") or ""
        details = {"location": loc}
        if loc:
            details["location_url"] = loc
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
        findings.append(
            Finding(
                rule="console/warning",
                severity=Severity.MINOR,
                title="Предупреждение в консоли",
                message=message.get("text", "")[:500],
                url=url,
                source="webscope.console",
            )
        )

    for request in ctx.failed_requests[:_MAX_PER_KIND]:
        status = request.get("status")
        res_url = request.get("url", "") or ""
        method = request.get("method", "GET") or "GET"
        failure = request.get("failure")
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
                details={"status": status, "resource": res_url},
            )
        )

    return findings
