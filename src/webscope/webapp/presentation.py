"""Представление данных в шаблонах: фильтры и небольшие обёртки.

Шаблоны не должны заниматься разбором ISO-дат, обрезкой адресов и
определением «тона» оценки. Здесь собраны чистые функции, которые можно
проверить отдельно от FastAPI и Jinja.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlsplit

from .storage import Run, Site


@dataclass(frozen=True)
class SiteCard:
    """Сайт и его последний прогон — единица списков на главной и в кабинете."""

    site: Site
    run: Run | None = None


def register_filters(env) -> None:
    """Регистрирует фильтры один раз при сборке приложения."""
    env.filters.update(
        {
            "dt": human_datetime,
            "short_url": short_url,
            "short_error": short_error,
            "score_tone": score_tone,
            "error_hint": error_hint,
            "ru_plural": ru_plural,
        }
    )


def ru_plural(value: int | str, one: str, few: str, many: str) -> str:
    """Русская форма слова для числа: 1 проверка, 2 проверки, 5 проверок.

    Используется в подписях метрик, где число выводится отдельно.
    """
    try:
        number = abs(int(value))
    except (TypeError, ValueError):
        return many
    if number % 10 == 1 and number % 100 != 11:
        return one
    if 2 <= number % 10 <= 4 and not 12 <= number % 100 <= 14:
        return few
    return many


def human_datetime(value: str | None) -> str:
    """ISO-время из базы → «16.11.2026, 14:05».

    Если строка не разбирается (старые записи), показываем её как есть —
    падать из-за даты страница не должна.
    """
    if not value:
        return "—"
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return str(value)[:16].replace("T", " ")
    return parsed.strftime("%d.%m.%Y, %H:%M")


def short_url(value: str | None, limit: int = 60) -> str:
    """Адрес для узкой колонки: без схемы и с многоточием в конце."""
    if not value:
        return "—"
    text = str(value)
    for prefix in ("https://", "http://"):
        if text.startswith(prefix):
            text = text[len(prefix) :]
            break
    if text.startswith("www."):
        text = text[4:]
    text = text.rstrip("/") or text
    limit = max(12, int(limit))
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def short_error(value: str | None, limit: int = 160) -> str:
    """Первая строка ошибки без шума и лишней длины."""
    if not value:
        return "проверка не удалась"
    first = str(value).strip().splitlines()[0]
    limit = max(20, int(limit))
    if len(first) <= limit:
        return first
    return first[: limit - 1].rstrip() + "…"


def score_tone(score: int | None) -> str:
    """Цвет оценки: зелёный, жёлтый или красный."""
    if score is None:
        return "bad"
    try:
        number = int(score)
    except (TypeError, ValueError):
        return "bad"
    if number >= 80:
        return "ok"
    if number >= 50:
        return "warn"
    return "bad"


def error_hint(message: str | None) -> str:
    """Человеческая подсказка к тексту ошибки сканера."""
    text = (message or "").lower()
    if any(token in text for token in ("авториз", "auth", "401", "login", "парол")):
        return "Проверьте настройки входа — логин/пароль или форму авторизации."
    if any(token in text for token in ("timeout", "таймаут", "connect", "недоступ")):
        return "Сайт не отвечает. Проверьте доступность или увеличьте таймаут."
    if "robots" in text:
        return "robots.txt запрещает обход. Проверьте настройки или доступность сайта."
    if any(token in text for token in ("dns", "name or service", "resolve")):
        return "Не удалось определить домен. Проверьте адрес сайта."
    if any(token in text for token in ("ssl", "certificate", "сертификат")):
        return "Проблема с HTTPS-сертификатом. Проверьте настройки домена."
    return "Проверьте доступность сайта и настройки. Можно запустить проверку повторно."


def display_host(value: str | None) -> str:
    """Короткое имя сайта без пути — для заголовков и подписей."""
    if not value:
        return "сайт"
    host = urlsplit(str(value)).hostname
    return host or short_url(value, 40)


__all__ = [
    "SiteCard",
    "display_host",
    "error_hint",
    "human_datetime",
    "register_filters",
    "score_tone",
    "short_error",
    "short_url",
]
