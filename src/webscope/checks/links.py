"""Ссылки: битые, безымянные, небезопасные.

Часть проверок требует сети (статус внутренних ссылок), поэтому они выполняются
с ограничением по количеству и таймауту — скан не должен упираться в сеть.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin, urlparse

from ..context import ScanContext
from ..models import Finding, Severity

COLLECT = r"""
() => {
  const u = window.__webscopeUtils;
  return Array.from(document.querySelectorAll('a[href]')).map((a) => ({
    href: a.getAttribute('href') || '',
    resolved: a.href || '',
    text: u.text(a).slice(0, 120),
    target: a.getAttribute('target') || '',
    rel: a.getAttribute('rel') || '',
    selector: u.cssPath(a),
    snippet: (a.outerHTML || '').slice(0, 200),
  }));
}
"""


def run(page: object, ctx: ScanContext) -> list[Finding]:
    links = page.evaluate(COLLECT) or []  # type: ignore[attr-defined]
    findings: list[Finding] = []
    url = ctx.final_url
    page_host = urlparse(url).netloc

    def add(rule: str, severity: Severity, title: str, message: str, **kwargs) -> None:
        findings.append(
            Finding(
                rule=rule,
                severity=severity,
                title=title,
                message=message,
                url=url,
                source="webscope.links",
                **kwargs,
            )
        )

    seen: set[str] = set()
    candidates: list[dict] = []

    for link in links:
        href = (link.get("href") or "").strip()
        resolved = (link.get("resolved") or "").strip()

        if href in {"", "#"} or href.lower().startswith("javascript:void"):
            add(
                "links/empty-href",
                Severity.MODERATE,
                "Ссылка без адреса",
                f'href="{href or "(пусто)"}" не ведёт ни в какое место — вероятно, обработчик потерялся.',
                selector=link.get("selector"),
                snippet=link.get("snippet"),
                details={"href": href},
            )
            continue

        if link.get("target") == "_blank" and "noopener" not in (link.get("rel") or "").lower():
            add(
                "links/target-blank-noopener",
                Severity.MODERATE,
                "target=_blank без rel=noopener",
                "Открытая вкладка получает доступ к window.opener.",
                selector=link.get("selector"),
                snippet=link.get("snippet"),
            )

        if url.startswith("https://") and resolved.startswith("http://"):
            add(
                "links/mixed-content",
                Severity.SERIOUS,
                "Смешанное содержимое (http на https-странице)",
                "Браузер может заблокировать или пометить ресурс как небезопасный.",
                selector=link.get("selector"),
                snippet=link.get("snippet"),
                details={"href": resolved},
            )

        parsed = urlparse(resolved)
        if parsed.scheme in {"http", "https"} and parsed.netloc == page_host and resolved not in seen:
            seen.add(resolved)
            candidates.append({"url": resolved, "selector": link.get("selector"), "text": link.get("text")})

    findings.extend(_check_internal_links(candidates, ctx))
    return findings


def _check_internal_links(candidates: list[dict], ctx: ScanContext) -> list[Finding]:
    """Проверяет HTTP-статус внутренних ссылок (с ограничением количества)."""
    if not candidates:
        return []

    import httpx

    limit = max(0, ctx.max_link_checks)
    targets = candidates[:limit]
    findings: list[Finding] = []
    timeout = httpx.Timeout(8.0, connect=4.0)

    def probe(link: dict) -> tuple[dict, int | None, str | None]:
        status: int | None = None
        error: str | None = None
        try:
            with httpx.Client(timeout=timeout, follow_redirects=True, verify=False) as client:
                response = client.head(link["url"])
                if response.status_code in (405, 501):
                    response = client.get(link["url"])
                status = response.status_code
        except Exception as exc:  # noqa: BLE001 - сетевые ошибки не должны ронять скан
            error = type(exc).__name__
        return link, status, error

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(probe, targets))

    for link, status, error in results:
        if error is not None:
            findings.append(
                Finding(
                    rule="links/unreachable",
                    severity=Severity.MODERATE,
                    title="Ссылка недоступна",
                    message=f"Не удалось получить ответ: {error}",
                    url=ctx.final_url,
                    selector=link.get("selector"),
                    source="webscope.links",
                    details={"href": link["url"]},
                )
            )
            continue
        if status is not None and status >= 400:
            findings.append(
                Finding(
                    rule="links/broken",
                    severity=Severity.SERIOUS if status >= 500 else Severity.MODERATE,
                    title=f"Битая ссылка (HTTP {status})",
                    message="Страница, на которую ведёт ссылка, отвечает ошибкой.",
                    url=ctx.final_url,
                    selector=link.get("selector"),
                    source="webscope.links",
                    details={"href": link["url"], "status": status},
                )
            )

    if len(candidates) > limit:
        findings.append(
            Finding(
                rule="links/limit-reached",
                severity=Severity.MINOR,
                title="Проверена не часть внутренних ссылок",
                message=f"Проверено {limit} из {len(candidates)} внутренних ссылок (лимит скана).",
                url=ctx.final_url,
                source="webscope.links",
            )
        )

    return findings


def resolve(base: str, href: str) -> str:
    """Абсолютизирует ссылку относительно базы."""
    return urljoin(base, href)
