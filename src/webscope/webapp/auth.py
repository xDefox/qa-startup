"""Вход в веб-интерфейс: пароль из окружения и подписанная cookie-сессия.

Раньше в приложении была страница входа, пароль по умолчанию ``dev`` и cookie
со значением ``auth``, которую не проверял ни один маршрут: данные всех сайтов
были доступны любому, кто дотянется до порта.

Здесь вход закрыт по умолчанию, как только задан ``WEBSCOPE_AUTH_PASSWORD``
(переменные: ``WEBSCOPE_AUTH_PASSWORD``, ``WEBSCOPE_AUTH_USER``). Пока пароль
не задан, приложение остаётся демо-режимом и печатает предупреждение при старте
(``webscope serve``). Cookie не хранит пароль: это HMAC от логина и пароля,
поэтому смена пароля разлогинивает всех, а украденная cookie ничего не раскрывает.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from urllib.parse import urlparse

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

COOKIE_NAME = "webscope_session"

# Методы без побочных эффектов: их не проверяем на CSRF.
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})

# Что доступно без входа: сам вход, healthcheck и раздача загруженных файлов
# (её открывает браузер-сканер без cookie; содержимое песочницы — см. app.py).
PUBLIC_PREFIXES = ("/auth/", "/healthz", "/__local/")


def auth_configured() -> bool:
    """Включён ли вход: задан непустой пароль в окружении."""
    return bool((os.environ.get("WEBSCOPE_AUTH_PASSWORD") or "").strip())


def auth_username() -> str:
    return (os.environ.get("WEBSCOPE_AUTH_USER") or "admin").strip() or "admin"


def _password() -> str:
    return os.environ.get("WEBSCOPE_AUTH_PASSWORD") or ""


def session_token() -> str:
    """Токен сессии: HMAC от логина и пароля (пароль наружу не попадает)."""
    return hmac.new(_password().encode("utf-8"), auth_username().encode("utf-8"), hashlib.sha256).hexdigest()


def check_credentials(username: str, password: str) -> bool:
    """Постоянное по времени сравнение логина и пароля."""
    return hmac.compare_digest(username.strip(), auth_username()) and hmac.compare_digest(password, _password())


def is_authenticated(request: Request) -> bool:
    token = request.cookies.get(COOKIE_NAME) or ""
    return bool(token) and hmac.compare_digest(token, session_token())


def is_public_path(path: str) -> bool:
    return any(path == prefix.rstrip("/") or path.startswith(prefix) for prefix in PUBLIC_PREFIXES)


def wants_json(request: Request) -> bool:
    """API отвечает JSON'ом, страницы — редиректом на форму входа."""
    return request.url.path.startswith("/api/") or "application/json" in request.headers.get("accept", "")


def unauthorized_response(request: Request) -> Response:
    if wants_json(request):
        return JSONResponse({"detail": "Требуется вход"}, status_code=401)
    target = request.url.path
    if request.url.query:
        target += f"?{request.url.query}"
    return RedirectResponse(url=f"/auth/login?next={target}", status_code=303)


def _same_origin(request: Request, candidate: str) -> bool:
    parsed = urlparse(candidate)
    if not parsed.netloc:
        return False
    expected = request.headers.get("host", "")
    return parsed.netloc.lower() == expected.lower()


def csrf_safe(request: Request) -> bool:
    """Совпадает ли Origin/Referer запроса с хостом приложения.

    Браузер шлёт ``Origin`` на все POST (с 2020 года и для same-origin), поэтому
    чужая форма с нашего домена отсекается. Запросы без обоих заголовков
    (curl, CI) пропускаем: cookie у них и так нет, а ломать интеграции незачем.
    """
    origin = request.headers.get("origin")
    if origin:
        return _same_origin(request, origin)
    referer = request.headers.get("referer")
    if referer:
        return _same_origin(request, referer)
    return True


def cookie_kwargs(request: Request | None = None) -> dict:
    """Параметры cookie: HttpOnly + SameSite, Secure на HTTPS.

    Secure выводится из схемы запроса, а не ставится всегда: `webscope serve`
    по умолчанию слушает http://127.0.0.1, и жёсткий Secure сделал бы вход
    невозможным (браузер не пришлёт такую cookie по http). За прокси схему
    сообщает ``X-Forwarded-Proto``.
    """
    secure = False
    if request is not None:
        forwarded = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip()
        secure = forwarded == "https" or request.url.scheme == "https"
    if os.environ.get("WEBSCOPE_INSECURE_COOKIES") == "1":
        secure = False
    elif os.environ.get("WEBSCOPE_SECURE_COOKIES") == "1":
        secure = True
    return {"key": COOKIE_NAME, "httponly": True, "samesite": "lax", "secure": secure, "path": "/"}


def login_page(request: Request, templates, *, error: str | None = None) -> HTMLResponse:
    return templates.TemplateResponse(request, "auth.html", {"error": error, "auth_enabled": auth_configured()})


def apply_headers(response: Response) -> Response:
    """Базовые заголовки безопасности для страниц приложения."""
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault("X-Frame-Options", "DENY")
    return response
