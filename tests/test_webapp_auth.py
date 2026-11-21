"""Вход и регистрация: аккаунты в БД, сессии, личный кабинет.

Проверяем не только «форма открылась», но и то, ради чего вход нужен:
пароль не хранится открытым, чужая cookie не подходит, у каждого пользователя
свои сайты, а выход действительно отзывает сессию.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from conftest import sign_in
from fastapi.testclient import TestClient

from webscope.webapp.app import create_app
from webscope.webapp.auth import COOKIE_NAME, auth_configured

PASSWORD = "test-password-123"


@pytest.fixture
def app(tmp_path: Path, stub_scanner, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("WEBSCOPE_AUTH_PASSWORD", raising=False)
    return create_app(
        db_path=tmp_path / "db.sqlite",
        scanner_func=stub_scanner,
        notifier=lambda **kwargs: [],
    )


@pytest.fixture
def client(app):
    with TestClient(app) as test_client:
        yield test_client


def register(client: TestClient, email: str = "user@example.com", password: str = PASSWORD):
    return client.post(
        "/auth/register",
        data={"email": email, "password": password, "password_confirm": password},
        follow_redirects=False,
    )


def test_auth_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WEBSCOPE_AUTH_PASSWORD", raising=False)
    assert auth_configured() is False


def test_pages_require_login(client: TestClient) -> None:
    for path in ("/dashboard", "/scan", "/sites/1", "/sites/1/settings", "/sites/1/history"):
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 303, path
        assert response.headers["location"].startswith("/auth/login")


def test_marketing_pages_are_public(client: TestClient) -> None:
    for path in ("/", "/landing"):
        assert client.get(path, follow_redirects=False).status_code == 200, path


def test_api_requires_login_with_401(client: TestClient) -> None:
    response = client.get("/api/sites")
    assert response.status_code == 401
    assert response.json()["detail"]


def test_healthz_stays_public(client: TestClient) -> None:
    assert client.get("/healthz").status_code == 200


def test_login_and_register_forms_render(client: TestClient) -> None:
    login = client.get("/auth/login")
    assert login.status_code == 200
    assert "Вход в кабинет" in login.text
    assert 'name="password"' in login.text
    assert "/auth/register" in login.text

    register_page = client.get("/auth/register")
    assert register_page.status_code == 200
    assert "Регистрация" in register_page.text
    assert 'name="password_confirm"' in register_page.text


def test_register_creates_account_and_logs_in(client: TestClient, app) -> None:
    response = register(client)
    assert response.status_code == 303
    assert response.headers["location"] == "/dashboard"

    page = client.get("/dashboard")
    assert page.status_code == 200
    assert "user@example.com" in page.text or "Кабинет" in page.text

    users = app.state.webscope.storage.get_user_by_email("user@example.com")
    assert users is not None
    assert users["password_hash"] != PASSWORD
    assert users["password_hash"].startswith("scrypt$")


def test_register_rejects_duplicate_email(client: TestClient) -> None:
    assert register(client, "dup@example.com").status_code == 303
    client.get("/auth/logout")
    response = register(client, "DUP@example.com")
    assert response.status_code == 200
    assert "уже зарегистрирован" in response.text


def test_register_validates_password(client: TestClient) -> None:
    short = client.post(
        "/auth/register",
        data={"email": "a@example.com", "password": "short", "password_confirm": "short"},
    )
    assert short.status_code == 200
    assert "не короче" in short.text

    mismatch = client.post(
        "/auth/register",
        data={"email": "b@example.com", "password": PASSWORD, "password_confirm": "other-pass-123"},
    )
    assert mismatch.status_code == 200
    assert "не совпадают" in mismatch.text


def test_login_with_wrong_password(client: TestClient) -> None:
    register(client)
    client.get("/auth/logout")

    response = client.post("/auth/login", data={"email": "user@example.com", "password": "nope"})
    assert response.status_code == 200
    assert "Неверный email или пароль" in response.text
    assert client.get("/dashboard", follow_redirects=False).status_code == 303


def test_login_sets_session_and_grants_access(client: TestClient) -> None:
    register(client)
    client.get("/auth/logout")

    response = client.post(
        "/auth/login",
        data={"email": "user@example.com", "password": PASSWORD, "next": "/sites"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/sites"

    page = client.get("/dashboard")
    assert page.status_code == 200
    assert "Кабинет" in page.text

    token = client.cookies.get(COOKIE_NAME)
    assert token and PASSWORD not in token
    assert ":" not in token  # случайный токен, а не user_id:подпись


def test_forged_cookie_is_rejected(client: TestClient) -> None:
    client.cookies.set(COOKIE_NAME, "auth")
    assert client.get("/dashboard", follow_redirects=False).status_code == 303


def test_logout_revokes_session(client: TestClient) -> None:
    register(client)
    token = client.cookies.get(COOKIE_NAME)
    assert token

    client.get("/auth/logout")
    # Возвращаем старую cookie: серверная сессия уже удалена.
    client.cookies.set(COOKIE_NAME, token)
    assert client.get("/dashboard", follow_redirects=False).status_code == 303


def test_csrf_blocks_foreign_origin(client: TestClient, app) -> None:
    register(client)
    response = client.post(
        "/sites",
        data={"url": "example.com"},
        headers={"Origin": "https://evil.example"},
        follow_redirects=False,
    )
    assert response.status_code == 403
    assert app.state.webscope.storage.list_sites() == []


def test_csrf_allows_same_origin(client: TestClient, app) -> None:
    register(client)
    response = client.post(
        "/sites",
        data={"url": "example.com"},
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert len(app.state.webscope.storage.list_sites()) == 1


def test_users_have_separate_cabinets(client: TestClient, app) -> None:
    register(client, "alice@example.com")
    created = client.post("/sites", data={"url": "alice-site.example"}, follow_redirects=False)
    assert created.status_code == 303
    site_id = int(created.headers["location"].rsplit("/", 1)[-1])

    client.get("/auth/logout")
    register(client, "bob@example.com")

    dashboard = client.get("/dashboard")
    assert dashboard.status_code == 200
    assert "alice-site.example" not in dashboard.text
    assert client.get(f"/sites/{site_id}", follow_redirects=False).status_code == 404
    assert client.get(f"/api/sites/{site_id}").status_code == 404
    assert client.get(f"/api/sites/{site_id}/report.txt").status_code == 404

    sites = client.get("/api/sites").json()["sites"]
    assert sites == []

    # Алиса после повторного входа видит свой сайт.
    client.get("/auth/logout")
    sign_in(client, "alice@example.com", register=False)
    alice_sites = client.get("/api/sites").json()["sites"]
    assert [site["id"] for site in alice_sites] == [site_id]


def test_first_user_adopts_sites_created_before_login(tmp_path: Path, stub_scanner) -> None:
    """База, накопленная до появления регистрации, не теряется."""
    db_path = tmp_path / "legacy.sqlite"
    app = create_app(db_path=db_path, scanner_func=stub_scanner, notifier=lambda **kw: [])
    app.state.webscope.storage.add_site("https://legacy.example")

    with TestClient(app) as client:
        assert register(client, "owner@example.com").status_code == 303
        sites = client.get("/api/sites").json()["sites"]
    assert [site["url"] for site in sites] == ["https://legacy.example"]


def test_session_cookie_survives_restart(tmp_path: Path, stub_scanner, monkeypatch: pytest.MonkeyPatch) -> None:
    """Сессия лежит в БД, поэтому перезапуск процесса не разлогинивает."""
    monkeypatch.delenv("WEBSCOPE_AUTH_PASSWORD", raising=False)
    db_path = tmp_path / "db.sqlite"
    first = create_app(db_path=db_path, scanner_func=stub_scanner, notifier=lambda **kw: [])
    with TestClient(first) as client:
        register(client, "stay@example.com")
        token = client.cookies.get(COOKIE_NAME)

    second = create_app(db_path=db_path, scanner_func=stub_scanner, notifier=lambda **kw: [])
    with TestClient(second) as client:
        client.cookies.set(COOKIE_NAME, token)
        assert client.get("/dashboard").status_code == 200


def test_password_is_not_written_to_database(tmp_path: Path, stub_scanner) -> None:
    app = create_app(db_path=tmp_path / "db.sqlite", scanner_func=stub_scanner, notifier=lambda **kw: [])
    with TestClient(app) as client:
        register(client, "secret@example.com", "very-secret-password")
    with sqlite3.connect(tmp_path / "db.sqlite") as conn:
        dump = "\n".join(conn.iterdump())
    assert "very-secret-password" not in dump
    assert "scrypt$" in dump


def test_env_admin_still_works(tmp_path: Path, stub_scanner, monkeypatch: pytest.MonkeyPatch) -> None:
    """WEBSCOPE_AUTH_PASSWORD остался аварийным входом для старых установок."""
    monkeypatch.setenv("WEBSCOPE_AUTH_PASSWORD", "env-password")
    monkeypatch.setenv("WEBSCOPE_AUTH_USER", "admin")
    app = create_app(db_path=tmp_path / "db.sqlite", scanner_func=stub_scanner, notifier=lambda **kw: [])
    with TestClient(app) as client:
        response = client.post(
            "/auth/login",
            data={"email": "admin", "password": "env-password"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert client.get("/dashboard").status_code == 200
