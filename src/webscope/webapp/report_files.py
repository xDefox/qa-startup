"""Форматы отчёта и имена файлов для скачивания.

Здесь нет ни FastAPI, ни шаблонов: только расширения, MIME-типы, рендереры
и чистка имени файла. Имя уходит в заголовок ``Content-Disposition``, поэтому
всё, что приходит от пользователя, приводится к безопасному виду до того, как
попадёт в ответ.
"""

from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import quote, urlsplit

from ..report import render_html, render_json, render_junit, render_plain, render_pdf, render_sarif
from .storage import Run, Site

# Форматы отчёта: расширение в URL, MIME-тип и подпись для кнопки «скачать».
REPORT_MEDIA_TYPES = {
    "html": "text/html; charset=utf-8",
    "json": "application/json",
    "txt": "text/plain; charset=utf-8",
    "xml": "application/xml",
    "sarif": "application/sarif+json",
    "pdf": "application/pdf",
}

REPORT_RENDERERS = {
    "html": render_html,
    "json": render_json,
    "txt": render_plain,
    "xml": render_junit,
    "sarif": render_sarif,
    "pdf": render_pdf,
}

DOWNLOAD_FORMATS = (
    {"ext": "html", "label": "HTML", "hint": "Открыть в браузере и сохранить"},
    {"ext": "json", "label": "JSON", "hint": "Для интеграций и своего дашборда"},
    {"ext": "txt", "label": "TXT", "hint": "Прочитать в терминале или письмом"},
    {"ext": "xml", "label": "JUnit", "hint": "Для CI: Jenkins, GitLab, pytest"},
    {"ext": "sarif", "label": "SARIF", "hint": "Для GitHub Code Scanning"},
    {"ext": "pdf", "label": "PDF", "hint": "Отчёт для рассылки и存档"},
)

# Сколько символов имени файла разрешаем: длиннее браузеры и файловые
# системы начинают обрезать по-своему.
MAX_FILENAME_STEM = 120


def safe_report_stem(value: str | None) -> str | None:
    """Имя файла от пользователя, приведённое к безопасному виду.

    Имя уходит в заголовок ``Content-Disposition``, поэтому всё, чем можно
    навредить, вычищается: переводы строк (инъекция в заголовок), путь
    (``../../etc/passwd`` — это имя, а не путь), кавычки, управляющие символы.
    Расширение, если пользователь его вписал, отбрасывается: его задаёт формат.

    Возвращает None, если после чистки ничего не осталось, — тогда берётся
    имя по умолчанию.
    """
    if not value:
        return None
    # только печатаемые символы: CR/LF в заголовке — это уже другая уязвимость
    cleaned = "".join(char for char in str(value) if char.isprintable())
    # имя файла, а не путь: берём последний сегмент
    cleaned = cleaned.replace("\\", "/").split("/")[-1].strip()
    stem, dot, tail = cleaned.rpartition(".")
    if dot and tail.lower() in REPORT_MEDIA_TYPES:
        cleaned = stem
    cleaned = "".join(char if (char.isalnum() or char in "-_. ") else "-" for char in cleaned)
    cleaned = " ".join(cleaned.split()).strip(" .-_")
    return cleaned[:MAX_FILENAME_STEM].strip(" .-_") or None


def default_report_stem(site: Site, run: Run) -> str:
    """Имя по умолчанию: домен и дата прогона.

    Unicode-домены, порты и IPv6 превращаются в дефисы, иначе в заголовке
    окажется что-то вроде ``https://пример.рф:8443/``.
    """
    host = urlsplit(site.url).hostname or "site"
    safe_host = re.sub(r"[^A-Za-z0-9.-]+", "-", host).strip("-.") or "site"
    day = (run.started_at or "")[:10]
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) is None:
        day = "report"
    return f"webscope-{safe_host}-{day}"


def download_filename(site: Site, run: Run, ext: str, name: str | None = None) -> str:
    """Имя файла отчёта: имя пользователя (если задал) плюс расширение формата."""
    stem = safe_report_stem(name) or default_report_stem(site, run)
    return f"{stem}.{ext}"


def content_disposition(filename: str, fallback: str | None = None) -> str:
    """Заголовок ``Content-Disposition`` для файла с любым именем.

    В ``filename`` по RFC 6266 допустим только ASCII, поэтому для кириллицы
    добавляется ``filename*`` в кодировке UTF-8, а в ``filename`` остаётся
    ASCII-запасной вариант: старые клиенты не увидят кракозябры. ``fallback`` —
    что показать такому клиенту; по умолчанию собирается из самого имени.
    """
    if filename.isascii():
        return f'attachment; filename="{filename}"'
    if fallback is None:
        stem, _, ext = filename.rpartition(".")
        fallback_stem = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip("-._") or "report"
        fallback = f"{fallback_stem}.{ext}" if ext else fallback_stem
    encoded = quote(filename, safe="")
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{encoded}"


def human_date(value: str | None) -> str | None:
    """Дата прогона по-человечески: 2026-10-30T09:15:00+00:00 → 30.10.2026."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).strftime("%d.%m.%Y")
    except ValueError:
        return None
