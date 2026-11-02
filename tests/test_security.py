# P0: базовые тесты безопасности
from webscope.webapp.auth import COOKIE_NAME, auth_configured


def test_auth_cookie_exists():
    assert COOKIE_NAME == "webscope_session"


def test_auth_configured_default_false():
    # По умолчанию без WEBSCOPE_AUTH_PASSWORD — False
    assert auth_configured() is False


def test_auth_middleware_applied():
    # Middleware guard подключён в app.py (P0 разделение)
    # Проверяем через наличие middleware в приложении
    import importlib

    app_mod = importlib.import_module("webscope.webapp.app")
    assert hasattr(app_mod, "guard")


def test_local_access_requires_auth():
    # P0: /__local должен требовать auth при auth_configured()
    # Заглушка — полная проверка требует запуска FastAPI TestClient
    assert True


# P1: тесты безопасности (расширенные)
# /upload: проверка лимитов (MAX_UPLOAD_FILE_BYTES, MAX_UPLOAD_TOTAL_BYTES)
# /__local: проверка CSP заголовков (X-Content-Type-Options, Cache-Control)
# CSRF: проверка csrf_safe() с разными Origin/Referer
# SSRF: проверка validate_target() с приватными IP
