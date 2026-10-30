"""Вход в кабинет: пароль, cookie, CSRF.

До аудита 2026-10-30 веб-интерфейс был открыт всем: `/api/sites` отдавал
список сайтов без авторизации, а cookie `auth` мог подделать кто угодно.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from webscope.webapp.app import create_app
from webscope.webapp.auth import COOKIE_NAME, auth_configured, session_token

PASSWORD = "s3cret-pass"
USERNAME = "admin"


@pytest.fixture
def guarded_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_scanner):
    monkeypatch.setenv("WEBSCOPE_AUTH_PASSWORD", PASSWORD)
    monkeypatch.setenv("WEBSCOPE_AUTH_USER", USERNAME)
    app = create_app(
        db_path=tmp_path / "db.sqlite",
        scanner_func=stub_scanner,
        notifier=lambda **kwargs: [],
    )
    with TestClient(app) as client:
        yield client, app


def test_auth_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WEBSCOPE_AUTH_PASSWORD", raising=False)
    assert auth_configured() is False


def test_pages_require_login(guarded_app) -> None:
    client, _app = guarded_app
    for path in ("/", "/sites/1", "/sites/1/settings", "/sites/1/history"):
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 303, path
        assert response.headers["location"].startswith("/auth/login")


def test_api_requires_login_with_401(guarded_app) -> None:
    client, _app = guarded_app
    response = client.get("/api/sites")
    assert response.status_code == 401
    assert response.json()["detail"]


def test_healthz_stays_public(guarded_app) -> None:
    client, _app = guarded_app
    assert client.get("/healthz").status_code == 200


def test_login_form_renders(guarded_app) -> None:
    """Раньше /auth/login падал с 500: шаблона auth.html не было."""
    client, _app = guarded_app
    response = client.get("/auth/login")
    assert response.status_code == 200
    assert "Вход в кабинет" in response.text
    assert 'name="password"' in response.text


def test_login_with_wrong_password(guarded_app) -> None:
    client, _app = guarded_app
    response = client.post("/auth/login", data={"username": USERNAME, "password": "nope"})
    assert response.status_code == 200
    assert "Неверные" in response.text
    assert client.get("/", follow_redirects=False).status_code == 303


def test_login_sets_session_and_grants_access(guarded_app) -> None:
    client, _app = guarded_app
    response = client.post(
        "/auth/login",
        data={"username": USERNAME, "password": PASSWORD, "next": "/sites"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/sites"

    page = client.get("/")
    assert page.status_code == 200
    assert "Проверьте свой сайт" in page.text

    # cookie не содержит пароля и подписана HMAC'ом
    token = client.cookies.get(COOKIE_NAME)
    assert token and PASSWORD not in token
    assert token == session_token()


def test_forged_cookie_is_rejected(guarded_app) -> None:
    """Раньше cookie со значением «auth» никто не проверял — её подделывал любой."""
    client, _app = guarded_app
    client.cookies.set(COOKIE_NAME, "auth")
    assert client.get("/", follow_redirects=False).status_code == 303


def test_csrf_blocks_foreign_origin(guarded_app) -> None:
    client, app = guarded_app
    client.post("/auth/login", data={"username": USERNAME, "password": PASSWORD})
    response = client.post(
        "/sites",
        data={"url": "example.com"},
        headers={"Origin": "https://evil.example"},
        follow_redirects=False,
    )
    assert response.status_code == 403
    assert app.state.storage.list_sites() == []


def test_csrf_allows_same_origin(guarded_app) -> None:
    client, app = guarded_app
    client.post("/auth/login", data={"username": USERNAME, "password": PASSWORD})
    response = client.post(
        "/sites",
        data={"url": "example.com"},
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert len(app.state.storage.list_sites()) == 1


def test_api_docs_are_closed(guarded_app) -> None:
    client, _app = guarded_app
    # без входа — редирект на форму, после входа — докуменации просто нет
    assert client.get("/docs", follow_redirects=False).status_code == 303
    client.post("/auth/login", data={"username": USERNAME, "password": PASSWORD})
    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404
