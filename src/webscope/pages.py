"""Классификация страниц: важно понимать, что именно мы проверили.

Если сайт закрыт авторизацией, сканер попадает на форму входа. Отчёт обязан
сказать об этом прямо, иначе владелец думает, что проверен весь кабинет.
"""

from __future__ import annotations

from urllib.parse import urlparse

_AUTH_PATH_MARKERS = ("/login", "/signin", "/sign-in", "/auth", "/sso", "/logon", "/signin")
_AUTH_HOST_MARKERS = ("auth.", "login.", "sso.", "id.", "account.")


def is_auth_url(url: str | None) -> bool:
    """Похоже ли, что это страница входа/SSO, а не рабочая страница сайта."""
    if not url:
        return False
    parsed = urlparse(url)
    path = (parsed.path or "").lower()
    host = (parsed.hostname or "").lower()
    if any(marker in path for marker in _AUTH_PATH_MARKERS):
        return True
    if any(host.startswith(marker) for marker in _AUTH_HOST_MARKERS):
        return True
    return "login" in (parsed.query or "").lower()


def auth_note(url: str | None) -> str | None:
    """Примечание к отчёту, если сайт закрыт авторизацией. Иначе None."""
    if not is_auth_url(url):
        return None
    return (
        "Проверена страница авторизации (сайт закрыт логином). "
        "Для полной проверки личного кабинета нужен тестовый логин/пароль."
    )


def redirect_note(requested: str | None, final: str | None) -> str | None:
    """Примечание, если сканер ушёл на другой хост/адрес. Иначе None."""
    if not requested or not final:
        return None
    req = urlparse(requested)
    fin = urlparse(final)
    if (req.hostname or "") != (fin.hostname or ""):
        return f"Запрошен {req.hostname or requested}, но сайт перенаправил на {fin.hostname or final}."
    if (req.path or "/") != (fin.path or "/"):
        return f"Запрошен путь {req.path or '/'}, но сайт перенаправил на {fin.path or '/'}."
    return None


_ASSET_SUFFIXES = (
    ".html",
    ".htm",
    ".xhtml",
    ".asp",
    ".aspx",
    ".php",
    ".jsp",
    ".md",
    ".txt",
    ".xml",
)


def not_a_page_note(final: str | None) -> str | None:
    """Адрес выглядит как файл, а не как страница сайта.

    Сканер всё равно строит отчёт, но владельцу важно понимать, почему балл
    низкий: у текстового/скачанного файла не бывает ни title, ни заголовков.
    """
    if not final:
        return None
    path = (urlparse(final).path or "").lower()
    if path.endswith(_ASSET_SUFFIXES):
        return (
            "Проверен файл, а не страница сайта: у него нет title, структуры и меню, "
            "поэтому часть находок — ожидаемые. Для оценки сайта укажите адрес его страницы."
        )
    return None


def page_notes(requested: str | None, final: str | None) -> list[str]:
    """Все пояснения о том, что реально было проверено."""
    notes: list[str] = []
    not_page = not_a_page_note(final)
    if not_page:
        notes.append(not_page)
    redirected = redirect_note(requested, final)
    if redirected:
        notes.append(redirected)
    auth = auth_note(final)
    if auth:
        notes.append(auth)
    return notes
