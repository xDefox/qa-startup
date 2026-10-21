"""MCP-сервер webscope.

Отдаёт три инструмента:
- ``scan_page``     — полный скан и результат в JSON;
- ``list_findings`` — краткий список находок;
- ``get_fix_prompt`` — готовое ТЗ для coding-агента по найденным проблемам.

Схема usage в Claude Code:

    claude mcp add webscope -- webscope mcp
"""

from __future__ import annotations

import time
from typing import Any

try:  # mcp >= 2.0
    from mcp.server.mcpserver import MCPServer as _Server
except ModuleNotFoundError:  # pragma: no cover - mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server

from .models import ScanResult, Severity
from .report import build_fix_prompt
from .scanner import scan

mcp = _Server(
    "webscope",
    instructions=(
        "webscope сканирует веб-страницу детерминированными проверками и возвращает находки. "
        "Типовой цикл: scan_page → get_fix_prompt → правка кода → повторный scan_page."
    ),
)

_CACHE: dict[str, tuple[float, ScanResult]] = {}
_CACHE_TTL_SECONDS = 300

_STATE: dict[str, Any] = {"allow_private": False}


def _cached_scan(url: str) -> ScanResult:
    now = time.monotonic()
    cached = _CACHE.get(url)
    if cached and now - cached[0] < _CACHE_TTL_SECONDS:
        return cached[1]
    result = scan(url, allow_private=bool(_STATE.get("allow_private")))
    _CACHE[url] = (now, result)
    return result


@mcp.tool()
def scan_page(url: str, checks: str = "", timeout_ms: int = 30000) -> dict:
    """Просканировать страницу и вернуть полный результат в JSON.

    Args:
        url: адрес страницы (http/https).
        checks: список проверок через запятую. Пусто — все проверки.
        timeout_ms: таймаут загрузки страницы.
    """
    selected = [name.strip() for name in checks.split(",") if name.strip()] or None
    result = scan(
        url,
        checks=selected,
        timeout_ms=timeout_ms,
        allow_private=bool(_STATE.get("allow_private")),
    )
    _CACHE[url] = (time.monotonic(), result)
    return result.to_dict()


@mcp.tool()
def list_findings(url: str, min_severity: str = "minor") -> list[dict]:
    """Краткий список находок по URL (с кэшем на 5 минут).

    Args:
        url: адрес страницы.
        min_severity: минимальная серьёзность: critical, serious, moderate, minor.
    """
    result = _cached_scan(url)
    limit = Severity(min_severity).rank
    return [
        {
            "rule": finding.rule,
            "severity": finding.severity.value,
            "title": finding.title,
            "message": finding.message,
            "selector": finding.selector,
            "snippet": finding.snippet,
            "help_url": finding.help_url,
        }
        for finding in result.findings
        if finding.severity.rank <= limit
    ]


@mcp.tool()
def get_fix_prompt(url: str, rules: list[str] | None = None) -> str:
    """Собрать готовое ТЗ для исправления находок (можно скормить coding-агенту).

    Args:
        url: адрес страницы.
        rules: ограничить выборку конкретными правилами.
    """
    result = _cached_scan(url)
    return build_fix_prompt(result, rules)


def serve(*, allow_private: bool = False) -> None:
    """Запускает MCP-сервер в stdio-режиме."""
    _STATE["allow_private"] = allow_private
    mcp.run()


def main() -> None:  # pragma: no cover
    serve()


if __name__ == "__main__":  # pragma: no cover
    main()
