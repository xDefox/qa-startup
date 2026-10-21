"""Проверки страницы.

Каждая проверка — чистая функция ``(page, ctx) -> list[Finding]``.
Проверки не знают про отчёты, MCP и CLI: это позволяет запускать их в любом контексте
и тестировать по отдельности.
"""

from __future__ import annotations

from collections.abc import Callable

from ..context import ScanContext
from ..models import Finding

CheckFn = Callable[[object, ScanContext], list[Finding]]


def _load() -> dict[str, CheckFn]:
    from . import a11y, console, content, forms, links, viewport

    return {
        "a11y": a11y.run,
        "content": content.run,
        "forms": forms.run,
        "links": links.run,
        "console": console.run,
        "viewport": viewport.run,
    }


REGISTRY: dict[str, CheckFn] = _load()

DEFAULT_CHECKS: tuple[str, ...] = ("a11y", "content", "forms", "links", "console", "viewport")

__all__ = ["DEFAULT_CHECKS", "REGISTRY", "CheckFn"]
