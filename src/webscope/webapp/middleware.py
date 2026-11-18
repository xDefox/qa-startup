"""HTTP-middleware: вход, CSRF и Content Security Policy."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse

from .auth import (
    SAFE_METHODS,
    apply_headers,
    auth_configured,
    csrf_safe,
    is_authenticated,
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


def install(app: FastAPI) -> None:
    """Подключает middleware в правильном порядке."""

    @app.middleware("http")
    async def guard(request: Request, call_next):
        """Вход и CSRF для всех маршрутов, кроме публичных."""
        if auth_configured() and not is_public_path(request.url.path):
            if request.method not in SAFE_METHODS and not csrf_safe(request):
                return PlainTextResponse("Запрос с чужого Origin отклонён", status_code=403)
            if not is_authenticated(request):
                return apply_headers(unauthorized_response(request))
        response = await call_next(request)
        return apply_headers(response)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        """CSP и базовые заголовки; локальные файлы задают политику сами."""
        response = await call_next(request)
        if not request.url.path.startswith("/__local/"):
            response.headers["Content-Security-Policy"] = CSP
        return response


__all__ = ["CSP", "install"]
