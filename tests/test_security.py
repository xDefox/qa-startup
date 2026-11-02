# P0: базовые тесты безопасности
import pytest
from webscope.webapp.auth import auth_configured, is_authenticated, COOKIE_NAME

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
