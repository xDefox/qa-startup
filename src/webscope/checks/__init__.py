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
    from . import a11y, console, content, forms, interaction, links, mobile, viewport

    return {
        "a11y": a11y.run,
        "content": content.run,
        "forms": forms.run,
        "interaction": interaction.run,
        "links": links.run,
        "console": console.run,
        "viewport": viewport.run,
        "mobile": mobile.run,
    }


REGISTRY: dict[str, CheckFn] = _load()

DEFAULT_CHECKS: tuple[str, ...] = (
    # Набор «что мешает оставить заявку». Это единственное, что видит
    # владелец сайта по умолчанию: мёртвые формы, перекрытые кнопки,
    # битые ссылки, ошибки JS/сети, мобильная прокрутка, формат
    # viewport-меты и мелкие цели касания.
    "interaction",
    "forms",
    "links",
    "console",
    "viewport",
    "mobile",
)

# Полный аудит: доступность и SEO-мелочи включаются только явно,
# через --checks a11y,content,... — чтобы не топить реальные проблемы
# в списке «полей без autocomplete».
ALL_CHECKS: tuple[str, ...] = (
    "a11y",
    "content",
    "forms",
    "interaction",
    "links",
    "console",
    "viewport",
    "mobile",
)

__all__ = ["ALL_CHECKS", "DEFAULT_CHECKS", "REGISTRY", "CheckFn"]
