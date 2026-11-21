"""Вход и регистрация: пользователи в SQLite, сессии в cookie.

Раньше кабинет был один на всех: логин и пароль брались из окружения, а cookie
была HMAC-подписью от них. Теперь пользователей может быть много, у каждого
свои сайты и отчёты.

* пароль хранится только как scrypt-хеш (``storage._hash_password``);
* cookie содержит случайный токен, в базе лежит его SHA-256 — украденная копия
  базы не даёт войти, а выход сразу отзывает сессию;
* сессия живёт ``WEBSCOPE_SESSION_DAYS`` дней (по умолчанию 30) и продлевается
  при каждом входе;
* ``WEBSCOPE_AUTH_PASSWORD`` остался как аварийный вход: при старте создаётся
  пользователь ``WEBSCOPE_AUTH_USER`` с этим паролем, если его ещё нет.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from .state import STATE_KEY

COOKIE_NAME = "webscope_session"

# Методы без побочных эффектов: их не проверяем на CSRF.
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})

# Что доступно без входа: витрина, здоровье, статика и сами страницы входа.
PUBLIC_PREFIXES = ("/auth/", "/healthz", "/__local/", "/landing", "/static/", "/webhook/")

MIN_PASSWORD_LENGTH = 8
MAX_EMAIL_LENGTH = 254


def auth_configured(storage=None) -> bool:
    """Настроен ли вход: есть пароль в окружении или хотя бы один пользователь.

    Функция осталась для обратной совместимости и шаблонов. Middleware теперь
    всегда требует вход на закрытых страницах, независимо от её результата.
    """
    if (os.environ.get("WEBSCOPE_AUTH_PASSWORD") or "").strip():
        return True
    if storage is not None:
        return storage.has_users()
    return False


def auth_username() -> str:
    return (os.environ.get("WEBSCOPE_AUTH_USER") or "admin").strip() or "admin"


def _password() -> str:
    return os.environ.get("WEBSCOPE_AUTH_PASSWORD") or ""


def session_token() -> str:
    """Старый env-токен (HMAC от логина и пароля) — только для аварийного входа."""
    return hmac.new(_password().encode("utf-8"), auth_username().encode("utf-8"), hashlib.sha256).hexdigest()


def check_credentials(username: str, password: str) -> bool:
    """Сверка с паролем из окружения (аварийный вход, постоянное время)."""
    if not _password():
        return False
    return hmac.compare_digest(username.strip(), auth_username()) and hmac.compare_digest(password, _password())


def session_days() -> int:
    raw = (os.environ.get("WEBSCOPE_SESSION_DAYS") or "").strip()
    try:
        value = int(raw)
    except ValueError:
        return 30
    return value if 1 <= value <= 365 else 30


def normalize_email(value: str) -> str:
    return (value or "").strip().lower()


def validate_registration(email: str, password: str, password_confirm: str) -> str | None:
    """Возвращает текст ошибки или None, если данные годятся."""
    email = normalize_email(email)
    if not email or "@" not in email or len(email) > MAX_EMAIL_LENGTH:
        return "Введите корректный email"
    if password != password_confirm:
        return "Пароли не совпадают"
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Пароль должен быть не короче {MIN_PASSWORD_LENGTH} символов"
    return None


def start_session(storage, user: dict, request: Request) -> str:
    """Создаёт сессию в БД и возвращает токен для cookie."""
    import secrets

    token = secrets.token_urlsafe(32)
    expires = (datetime.now(UTC) + timedelta(days=session_days())).isoformat()
    storage.create_session(user["id"], token, expires)
    storage.purge_expired_sessions()
    return token


def end_session(storage, request: Request) -> None:
    token = request.cookies.get(COOKIE_NAME) if request else ""
    if storage is not None and token:
        storage.delete_session(token)


def bootstrap_env_admin(storage) -> None:
    """Создаёт аварийного пользователя из env, если его ещё нет."""
    if not _password():
        return
    email = auth_username()
    if storage.user_exists(email):
        return
    user_id = storage.create_user(email, _password())
    if storage.count_users() == 1:
        storage.adopt_orphan_data(user_id)


def _get_storage(request: Request):
    state = getattr(request.app.state, STATE_KEY, None)
    return getattr(state, "storage", None) if state else None


def get_current_user(request: Request) -> dict | None:
    """Текущий пользователь или None. Результат кэшируется в request.state."""
    cached = getattr(request.state, "user", None)
    if cached is not None:
        return cached
    token = request.cookies.get(COOKIE_NAME) or ""
    storage = _get_storage(request)
    user = storage.session_user(token) if (storage is not None and token) else None
    if user is None and token and auth_configured() and hmac.compare_digest(token, session_token()):
        # Аварийный вход по паролю из окружения (старые установки).
        return {"id": 0, "email": auth_username(), "is_admin": True, "created_at": ""}
    request.state.user = user
    return user


def is_authenticated(request: Request) -> bool:
    return get_current_user(request) is not None


def public_user(request: Request) -> dict | None:
    """Пользователь для шаблонов: id, email, имя, роль."""
    user = get_current_user(request)
    if user is None:
        return None
    storage = _get_storage(request)
    return {
        "id": user.get("id", 0),
        "email": user.get("email", ""),
        "username": user.get("email", ""),
        "is_admin": (storage.is_admin(user["id"]) if storage and user.get("id") else bool(user.get("is_admin"))),
        "created_at": user.get("created_at", ""),
    }


def is_public_path(path: str) -> bool:
    # Корень — витрина продукта, а не часть кабинета: открываем ровно "/",
    # не задевая остальные страницы приложения.
    if path == "/":
        return True
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


def login_page(request: Request, templates, *, error: str | None = None, next_url: str = "") -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "auth.html",
        {"error": error, "auth_enabled": auth_configured(_get_storage(request)), "next": next_url},
    )


def register_page(
    request: Request, templates, *, error: str | None = None, email: str = ""
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "auth_register.html",
        {"error": error, "email": email, "min_password": MIN_PASSWORD_LENGTH},
    )


def safe_next(value: str | None, default: str = "/dashboard") -> str:
    """Только локальный путь: открытый редирект через ``next`` не нужен."""
    if value and value.startswith("/") and not value.startswith("//"):
        return value
    return default


def apply_headers(response: Response) -> Response:
    """Базовые заголовки безопасности для страниц приложения."""
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault("X-Frame-Options", "DENY")
    return response
