"""Битые внутренние ссылки — только подтверждённые 4xx/5xx, плюс типовые
проблемы переходов: target="_blank" без noopener, пустой href, ресурсы по http.

Ссылка — это путь клиента к заявке. Поэтому проверяем только переходы внутри
сайта и только реальные ответы 404/410/5xx. Таймауты, 401/403 (закрытые
разделы), 429 (лимит запросов), якоря и «пустые» href из JavaScript-кнопок
не считаются дефектом: владельцу нечего исправлять.
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin, urlparse

import httpx

from ..context import ScanContext
from ..credscope import strip_out_of_scope_headers
from ..models import Finding, Severity
from ..netguard import GuardedTransport

_DESTRUCTIVE_PATH = re.compile(r"/(logout|signout|log-out|delete|remove|unsubscribe)(/|$)", re.IGNORECASE)

COLLECT = r"""
() => {
  const u = window.__webscopeUtils;
  return Array.from(document.querySelectorAll('a[href]'))
    .filter((a) => a.getAttribute('data-testid') === null && a.getAttribute('data-qa') === null)
    .filter((a) => a.getAttribute('aria-hidden') !== 'true')
    .map((a) => ({
    href: a.getAttribute('href') || '',
    resolved: a.href || '',
    text: u.text(a).slice(0, 120),
    target: a.getAttribute('target') || '',
    rel: a.getAttribute('rel') || '',
    role: a.getAttribute('role') || '',
    selector: u.cssPath(a),
    snippet: (a.outerHTML || '').slice(0, 200),
  }));
}
"""

# Ресурсы по http:// на https-странице — mixed content (links/mixed-content).
MIXED_COLLECT = r"""
() => {
  const u = window.__webscopeUtils;
  const out = [];
  for (const el of Array.from(document.querySelectorAll(
    'a[href], img[src], script[src], iframe[src], link[href], video[src], source[src], embed[src], object[data], input[src]'
  ))) {
    const raw = (el.getAttribute('href') || el.getAttribute('src') || el.getAttribute('data') || '').trim();
    if (raw.toLowerCase().startsWith('http://')) {
      out.push({ selector: u.cssPath(el), snippet: (el.outerHTML || '').slice(0, 200) });
    }
  }
  return out;
}
"""


def run(page: object, ctx: ScanContext) -> list[Finding]:
    links = page.evaluate(COLLECT) or []  # type: ignore[attr-defined]
    findings: list[Finding] = []
    url = ctx.final_url
    page_host = urlparse(url).netloc

    # links/target-blank-noopener: target="_blank" без noopener — вкладка получает доступ к сайту.
    for a in links:
        if (a.get("target") or "").strip().lower() != "_blank":
            continue
        rel = {token.strip().lower() for token in (a.get("rel") or "").split()}
        if "noopener" not in rel:
            findings.append(
                Finding(
                    rule="links/target-blank-noopener",
                    severity=Severity.MINOR,
                    title="Ссылка с target=\"_blank\" без rel=\"noopener\"",
                    message="Открытая вкладка получает доступ к вашему сайту — укажите rel=\"noopener\".",
                    url=url,
                    selector=a.get("selector"),
                    snippet=a.get("snippet"),
                    source="webscope.links",
                ),
            )

    # links/empty-href: ссылка с пустым href — клик не ведёт никуда.
    for a in links:
        if (a.get("href") or "").strip() != "":
            continue
        if (a.get("role") or "").strip().lower() == "button":
            continue  # семантика кнопки: имена ловят content/forms
        findings.append(
            Finding(
                rule="links/empty-href",
                severity=Severity.MODERATE,
                title="Ссылка без адреса",
                message="У ссылки пустой href — клик не даёт эффекта.",
                url=url,
                selector=a.get("selector"),
                snippet=a.get("snippet"),
                source="webscope.links",
            ),
        )

    # links/mixed-content — на https-странице ресурсы по http считаются mixed content.
    if urlparse(url).scheme == "https":
        mixed_seen: set[str] = set()
        try:
            mixed = page.evaluate(MIXED_COLLECT) or []  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - подготовка к проверке не должна ронять скан
            mixed = []
        for item in mixed[:5]:
            selector = item.get("selector") or ""
            if selector in mixed_seen:
                continue
            mixed_seen.add(selector)
            findings.append(
                Finding(
                    rule="links/mixed-content",
                    severity=Severity.MODERATE,
                    title="Ресурс загружается по http",
                    message=(
                        "Ресурс грузится по http:// — на https-странице браузер может "
                        "заблокировать его и показать «небезопасное» предупреждение."
                    ),
                    url=url,
                    selector=selector or None,
                    snippet=item.get("snippet"),
                    source="webscope.links",
                ),
            )

    seen: set[str] = set()
    candidates: list[dict] = []

    for link in links:
        href = (link.get("href") or "").strip()
        resolved = (link.get("resolved") or "").strip()

        # Якоря, пустые href и javascript: — это кнопки/меню, а не переходы.
        if not href or href == "#" or href.lower().startswith("javascript:"):
            continue

        parsed = urlparse(resolved)
        if parsed.scheme not in {"http", "https"} or parsed.netloc != page_host:
            continue

        # Один и тот же документ с якорем — не отдельная страница.
        if resolved.split("#", 1)[0] == url.split("#", 1)[0]:
            continue

        if _DESTRUCTIVE_PATH.search(parsed.path or ""):
            # GET по /logout или /delete — не проверяем: это действие, а не ссылка.
            continue

        if resolved not in seen:
            seen.add(resolved)
            candidates.append(
                {
                    "url": resolved,
                    "selector": link.get("selector"),
                    "text": (link.get("text") or "").strip(),
                },
            )

    findings.extend(_check_internal_links(candidates, ctx))
    return findings


# Ошибки, которые означают «не дождались», а не «ссылки нет». httpx бросает
# свои исключения по имени класса, тут же оказывается и socket.timeout.
_TIMEOUT_ERRORS = frozenset(
    {"TimeoutException", "ConnectTimeout", "ReadTimeout", "WriteTimeout", "PoolTimeout", "TimeoutError"},
)


def _error_rule(error: str) -> tuple[str, Severity]:
    """Правило и серьёзность для сетевой ошибки при проверке ссылки.

    Таймаут — свойство сети и терпения сканера, а не дефект страницы: чинить
    владельцу сайта нечего, поэтому такое правило диагностическое.
    """
    if error in _TIMEOUT_ERRORS:
        return "links/timeout", Severity.MINOR
    return "links/unreachable", Severity.MODERATE


def _check_internal_links(candidates: list[dict], ctx: ScanContext) -> list[Finding]:
    """Проверяет HTTP-статус внутренних ссылок (с ограничением количества).

    Клиент один на всю проверку: соединения переиспользуются, TLS проверяется
    (иначе «битые ссылки» на самом деле означают «наш сканер не поверил
    сертификату»), а запросы на непубличные адреса блокируются тем же
    транспортом, что и в краулере. На защищённом сайте запрос без кредов
    получает 401 — ложную «битую ссылку», — поэтому проверка идёт с теми же
    заголовками авторизации, что и скан (ctx.site_headers), но только для
    хостов страницы: редирект на чужой хост секреты снимает.
    """
    if not candidates:
        return []

    findings: list[Finding] = []
    timeout = httpx.Timeout(8.0, connect=4.0)
    # Один клиент (и одно соединение на хост) на все ссылки: httpx.Client
    # потокобезопасен, а создание клиента на каждую ссылку рвало пул соединений.
    transport = GuardedTransport(allow_private=ctx.allow_private)
    results: list[tuple[dict, int | None, str | None]] = []
    with httpx.Client(
        timeout=timeout,
        follow_redirects=True,
        transport=transport,
        headers=ctx.site_headers or None,
        event_hooks={"request": [strip_out_of_scope_headers(ctx.final_url)]},
    ) as client:

        def probe(link: dict) -> tuple[dict, int | None, str | None]:
            status: int | None = None
            error: str | None = None
            try:
                response = client.head(link["url"])
                # Многие CDN отвечают 403/405 на HEAD, хотя GET отдаёт страницу.
                if response.status_code in (403, 405, 501):
                    response = client.get(link["url"])
                status = response.status_code
            except Exception as exc:  # noqa: BLE001 - сетевые ошибки не должны ронять скан
                error = type(exc).__name__
            return link, status, error

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(probe, candidates))

    for link, status, error in results:
        if error is not None:
            rule, severity = _error_rule(error)
            if rule == "links/timeout":
                # Не дождались — это про сеть и терпение сканера, а не про сайт.
                continue
            findings.append(
                Finding(
                    rule=rule,
                    severity=severity,
                    title="Ссылка недоступна",
                    message=f"Не удалось получить ответ: {error}",
                    url=ctx.final_url,
                    selector=link.get("selector"),
                    source="webscope.links",
                    details={"href": link["url"], "error": error, "text": link.get("text")},
                ),
            )
            continue

        if status is None:
            continue
        # Закрытый раздел, лимит запросов и «не туда» редирект — не битая ссылка.
        if status in {401, 403, 429}:
            continue
        if status >= 400:
            findings.append(
                Finding(
                    rule="links/broken",
                    severity=Severity.SERIOUS if status >= 500 else Severity.MODERATE,
                    title=f"Битая ссылка (HTTP {status})",
                    message=(
                        f"Ссылка «{link.get('text') or link['url']}» ведёт на страницу, "
                        f"которая отвечает HTTP {status}."
                    ),
                    url=ctx.final_url,
                    selector=link.get("selector"),
                    source="webscope.links",
                    details={"href": link["url"], "status": status, "text": link.get("text")},
                ),
            )

    return findings


def resolve(base: str, href: str) -> str:
    """Абсолютизирует ссылку относительно базы."""
    return urljoin(base, href)
