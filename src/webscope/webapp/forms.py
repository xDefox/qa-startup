"""Разбор полей веб-формы в колонки базы."""

from __future__ import annotations


def auth_fields(
    *,
    enabled: str,
    kind: str,
    login: str,
    password: str,
    login_url: str,
    previous_password: str | None = None,
) -> dict:
    """Сводит поля формы «нужна авторизация» к колонкам базы.

    Выключенная галочка или пустой логин чистят вход. Пустой пароль при
    сохранении означает «не менять» — в форме он никогда не предзаполнен.
    """
    login = login.strip()
    if not enabled or not login:
        return {"auth_kind": None, "auth_login": None, "auth_password": None, "auth_login_url": None}
    if kind not in ("basic", "form"):
        kind = "basic"
    login_url = login_url.strip()
    if login_url and not login_url.startswith(("http://", "https://")):
        login_url = f"https://{login_url}"  # пользователь часто пишет домен без схемы
    return {
        "auth_kind": kind,
        "auth_login": login,
        "auth_password": password or (previous_password or ""),
        "auth_login_url": (login_url or None) if kind == "form" else None,
    }
