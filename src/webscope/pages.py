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


def page_notes(requested: str | None, final: str | None) -> list[str]:
    """Все пояснения о том, что реально было проверено."""
    notes: list[str] = []
    redirected = redirect_note(requested, final)
    if redirected:
        notes.append(redirected)
    auth = auth_note(final)
    if auth:
        notes.append(auth)
    return notes
