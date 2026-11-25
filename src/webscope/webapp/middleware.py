"""HTTP-middleware: вход, CSRF и Content Security Policy."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse

from .auth import (
    SAFE_METHODS,
    apply_headers,
    csrf_safe,
    get_current_user,
    is_public_path,
    unauthorized_response,
)

CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self'; "
    "img-src 'self' data:; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self';"
)

# S9: дополнительно жесткие заголовки безопасности
HSTS = "max-age=31536000; includeSubDomains; preload"
PERMISSIONS_POLICY = "camera=(), microphone=(), geolocation=(), payment=()"


def install(app: FastAPI) -> None:
    """Подключает middleware в правильном порядке."""

    @app.middleware("http")
    async def guard(request: Request, call_next):
        """Вход и CSRF для всех маршрутов, кроме публичных.

        Вход требуется всегда. Пока пользователей нет, кабинет пуст, а
        единственная доступная точка входа — регистрация.
        """
        user = get_current_user(request)
        if not is_public_path(request.url.path):
            if request.method not in SAFE_METHODS and not csrf_safe(request):
                return PlainTextResponse("Запрос с чужого Origin отклонён", status_code=403)
            if user is None:
                return apply_headers(unauthorized_response(request))
        response = await call_next(request)
        return apply_headers(response)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        """CSP и базовые заголовки; локальные файлы задают политику сами."""
        response = await call_next(request)
        if not request.url.path.startswith("/__local/"):
            response.headers["Content-Security-Policy"] = CSP
            # S9: HSTS — только если запрос был по HTTPS, иначе не имеет смысла
            # и ломает http-only деплойменты. Схему определяем по X-Forwarded-Proto.
            forwarded = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip()
            if forwarded == "https" or request.url.scheme == "https":
                response.headers["Strict-Transport-Security"] = HSTS
            response.headers["Permissions-Policy"] = PERMISSIONS_POLICY
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Referrer-Policy"] = "same-origin"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["X-XSS-Protection"] = "1; mode=block"
            response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        return response


__all__ = ["CSP", "install"]
