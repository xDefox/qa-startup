"""Фича «нужна авторизация»: хранилище кредов, веб-форма и живой вход движком.

Без браузера: модель учётных данных, миграция старой базы, маршруты формы,
передача кредов в сканер. С браузером (marker browser): Chromium реально
входит на локальный сервер — и заголовком Basic, и формой логина.
"""

from __future__ import annotations

import base64
import socket
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

import pytest
from fastapi.testclient import TestClient

from webscope.cli import _auth_from_args, build_parser
from webscope.crawler import crawl
from webscope.models import AuthCredentials, ScanResult
from webscope.scanner import ScanError, scan, scan_site
from webscope.webapp.app import create_app
from webscope.webapp.scheduler import CrawlOutcome, Monitor, ScanOptions
from webscope.webapp.storage import Storage

LOGIN = "admin"
PASSWORD = "secret"
BASIC_HEADER = "Basic " + base64.b64encode(f"{LOGIN}:{PASSWORD}".encode()).decode()

SECRET_PAGE = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><title>Секретная страница</title></head>
<body><h1>Секрет</h1></body></html>"""

FORM_PAGE = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><title>Вход</title></head>
<body>
  <h1>Вход на сайт</h1>
  <form method="post" action="/login">
    <label>Логин <input type="text" name="user"></label>
    <label>Пароль <input type="password" name="password"></label>
    <button type="submit">Войти</button>
  </form>
</body></html>"""

PRIVATE_PAGE = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><title>Личный кабинет</title></head>
<body><h1>Здравствуйте!</h1></body></html>"""

OPEN_PAGE = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><title>Открытая страница</title></head>
<body><p>Доступ без входа.</p></body></html>"""

EMPTY_401 = "<html><head></head><body>401</body></html>"


# --- локальные серверы для браузерных тестов ---


class _QuietHandler(BaseHTTPRequestHandler):
    def log_message(self, *args, **kwargs) -> None:
        """Тишина в тестах: логи HTTP-сервера не нужны."""

    def _finish(self, html: str) -> None:
        payload = html.encode()
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _page(self, status: int, html: str) -> None:
        self.send_response(status)
        self._finish(html)


class _BasicHandler(_QuietHandler):
    """Сайт за basic-паролем: чужому клиенту — 401 с вызовом авторизации."""

    def do_GET(self) -> None:
        if self.headers.get("Authorization") != BASIC_HEADER:
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="webscope-test"')
            self._finish(EMPTY_401)
            return
        self._page(200, SECRET_PAGE)


class _FormHandler(_QuietHandler):
    """Сайт с формой входа: сессия живёт в cookie, без неё — редирект на /login."""

    def do_GET(self) -> None:
        if self.path.startswith("/login"):
            self._page(200, FORM_PAGE)
        elif self.path.startswith("/open"):
            self._page(200, OPEN_PAGE)
        elif "session=ok" in self.headers.get("Cookie", ""):
            self._page(200, PRIVATE_PAGE)
        else:
            self.send_response(302)
            self.send_header("Location", "/login")
            self.end_headers()

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        fields = parse_qs(self.rfile.read(length).decode("utf-8", "replace"))
        if fields.get("user", [""])[0] == LOGIN and fields.get("password", [""])[0] == PASSWORD:
            self.send_response(302)
            self.send_header("Location", "/")
            self.send_header("Set-Cookie", "session=ok; Path=/")
            self.end_headers()
        else:
            self._page(200, FORM_PAGE)  # ошибка входа: форма остаётся на месте


def _serve(handler_class: type[BaseHTTPRequestHandler]):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = ThreadingHTTPServer(("127.0.0.1", port), handler_class)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{port}"


@pytest.fixture()
def basic_server():
    server, url = _serve(_BasicHandler)
    try:
        yield url
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture()
def form_server():
    server, url = _serve(_FormHandler)
    try:
        yield url
    finally:
        server.shutdown()
        server.server_close()


# --- модель и хранилище ---


def test_auth_credentials_rejects_unknown_kind() -> None:
    with pytest.raises(ValueError, match="Неизвестный тип авторизации"):
        AuthCredentials(kind="oauth", login="admin")


def test_storage_saves_auth_and_builds_credentials(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "db.sqlite")
    site = storage.add_site(
        "https://site.com/",
        auth_kind="form",
        auth_login=LOGIN,
        auth_password=PASSWORD,
        auth_login_url="https://site.com/wp-admin",
    )
    loaded = storage.get_site(site.id)
    assert loaded is not None
    assert loaded.has_auth
    assert loaded.auth_credentials() == AuthCredentials(
        kind="form", login=LOGIN, password=PASSWORD, login_url="https://site.com/wp-admin"
    )
    storage.close()


def test_storage_site_without_auth_has_no_credentials(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "db.sqlite")
    site = storage.add_site("https://site.com/")
    assert not site.has_auth
    assert site.auth_credentials() is None
    storage.close()


def test_site_to_dict_never_exposes_password(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "db.sqlite")
    site = storage.add_site("https://site.com/", auth_kind="basic", auth_login=LOGIN, auth_password=PASSWORD)
    payload = site.to_dict()
    assert payload["has_auth"] is True
    assert payload["auth_kind"] == "basic"
    assert "auth_password" not in payload
    assert PASSWORD not in str(payload)
    storage.close()


def test_update_site_auth_and_clear(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "db.sqlite")
    site = storage.add_site("https://site.com/")
    storage.update_site(site.id, auth_kind="basic", auth_login="a", auth_password="b", auth_login_url=None)
    assert storage.get_site(site.id).has_auth
    storage.update_site(site.id, auth_kind=None, auth_login=None, auth_password=None, auth_login_url=None)
    assert not storage.get_site(site.id).has_auth
    storage.close()


def test_migrate_adds_auth_columns_to_old_db(tmp_path: Path) -> None:
    """База первой версии (без колонок авторизации) дозаполняется миграцией."""
    path = tmp_path / "old.sqlite"
    connection = sqlite3.connect(path)
    connection.execute(
        """
        CREATE TABLE sites (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            url             TEXT NOT NULL UNIQUE,
            email           TEXT,
            telegram_chat   TEXT,
            schedule        TEXT NOT NULL DEFAULT 'off',
            interval_days   INTEGER NOT NULL DEFAULT 7,
            next_run_at     TEXT,
            created_at      TEXT NOT NULL
        )
        """
    )
    connection.execute(
        "INSERT INTO sites (url, created_at) VALUES (?, ?)",
        ("https://old.com/", "2024-01-01T00:00:00+00:00"),
    )
    connection.commit()
    connection.close()

    storage = Storage(path)  # init_db прогоняет SCHEMA + миграции
    old = storage.get_site(1)
    assert old is not None
    assert not old.has_auth
    site = storage.add_site("https://new.com/", auth_kind="basic", auth_login=LOGIN, auth_password=PASSWORD)
    assert storage.get_site(site.id).has_auth
    storage.close()


# --- монитор: креды сайта попадают в опции сканера ---


def _empty_result() -> ScanResult:
    result = ScanResult(url="https://site.com/", final_url="https://site.com/", title="Сайт")
    result.pages_scanned = 1
    return result


def test_monitor_passes_site_auth_into_scanner(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "db.sqlite")
    site = storage.add_site("https://site.com/", auth_kind="basic", auth_login=LOGIN, auth_password=PASSWORD)
    seen: dict = {}

    def scanner(url: str, options: ScanOptions) -> CrawlOutcome:
        seen["auth"] = options.auth
        return CrawlOutcome(_empty_result())

    monitor = Monitor(storage, ScanOptions(), scanner_func=scanner)
    monitor.run_site(site)
    assert seen["auth"] == AuthCredentials(kind="basic", login=LOGIN, password=PASSWORD)

    plain = storage.add_site("https://plain.com/")
    monitor.run_site(plain)
    assert seen["auth"] is None
    storage.close()


# --- CLI: флаги входа ---


def test_cli_auth_flags_build_credentials() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "crawl",
            "example.com",
            "--login",
            LOGIN,
            "--password",
            PASSWORD,
            "--auth",
            "form",
            "--login-url",
            "example.com/wp-admin",
        ]
    )
    assert _auth_from_args(args) == AuthCredentials(
        kind="form", login=LOGIN, password=PASSWORD, login_url="example.com/wp-admin"
    )
    assert _auth_from_args(parser.parse_args(["crawl", "example.com"])) is None


def test_cli_password_falls_back_to_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WEBSCOPE_PASSWORD", "envpw")
    parser = build_parser()
    args = parser.parse_args(["scan", "example.com", "--login", LOGIN])
    assert _auth_from_args(args) == AuthCredentials(kind="basic", login=LOGIN, password="envpw")


# --- веб-форма ---


@pytest.fixture()
def web(tmp_path: Path):
    app = create_app(
        db_path=tmp_path / "db.sqlite",
        scanner_func=lambda url, options: CrawlOutcome(_empty_result()),
        notifier=lambda **kwargs: [],
    )
    with TestClient(app) as client:
        yield client, app.state.storage


def test_index_renders_auth_checkbox(web) -> None:
    client, _ = web
    response = client.get("/")
    assert response.status_code == 200
    assert "Нужна авторизация" in response.text
    assert 'name="auth_enabled"' in response.text
    assert 'name="auth_login"' in response.text
    assert 'name="auth_password"' in response.text
    assert 'name="auth_login_url"' in response.text


def test_create_site_with_auth_stores_credentials(web) -> None:
    client, storage = web
    response = client.post(
        "/sites",
        data={
            "url": "example.com",
            "auth_enabled": "1",
            "auth_kind": "form",
            "auth_login": LOGIN,
            "auth_password": PASSWORD,
            "auth_login_url": "example.com/wp-admin",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    site = storage.list_sites()[0]
    assert site.has_auth
    assert site.auth_credentials() == AuthCredentials(
        kind="form", login=LOGIN, password=PASSWORD, login_url="example.com/wp-admin"
    )


def test_create_site_auth_requires_login(web) -> None:
    client, storage = web
    response = client.post(
        "/sites",
        data={"url": "example.com", "auth_enabled": "1", "auth_password": PASSWORD},
        follow_redirects=False,
    )
    assert response.status_code == 400
    assert "логин" in response.text.lower()
    assert storage.list_sites() == []


def test_create_site_without_checkbox_stores_nothing(web) -> None:
    client, storage = web
    client.post(
        "/sites",
        data={"url": "example.com", "auth_login": LOGIN, "auth_password": PASSWORD},
        follow_redirects=False,
    )
    site = storage.list_sites()[0]
    assert not site.has_auth
    assert site.auth_credentials() is None


def test_settings_page_shows_auth_without_password(web) -> None:
    client, _storage = web
    response = client.post(
        "/sites",
        data={
            "url": "example.com",
            "auth_enabled": "1",
            "auth_kind": "basic",
            "auth_login": LOGIN,
            "auth_password": PASSWORD,
        },
        follow_redirects=False,
    )
    site_id = int(response.headers["location"].rstrip("/").split("/")[-1])

    page = client.get(f"/sites/{site_id}/settings")
    assert 'name="auth_enabled"' in page.text
    assert "checked" in page.text
    assert f'value="{LOGIN}"' in page.text
    assert PASSWORD not in page.text  # пароль не предзаполняем и не показываем


def test_settings_empty_password_keeps_old(web) -> None:
    client, storage = web
    response = client.post(
        "/sites",
        data={
            "url": "example.com",
            "auth_enabled": "1",
            "auth_kind": "basic",
            "auth_login": LOGIN,
            "auth_password": PASSWORD,
        },
        follow_redirects=False,
    )
    site_id = int(response.headers["location"].rstrip("/").split("/")[-1])

    # пустой пароль при сохранении — «не менять»
    client.post(
        f"/sites/{site_id}/settings",
        data={"schedule": "off", "auth_enabled": "1", "auth_kind": "basic", "auth_login": LOGIN, "auth_password": ""},
    )
    assert storage.get_site(site_id).auth_password == PASSWORD

    # сняли галочку — вход выключен полностью
    client.post(f"/sites/{site_id}/settings", data={"schedule": "off"})
    assert not storage.get_site(site_id).has_auth


# --- краулер шлёт заголовок авторизации (без браузера) ---


def test_crawl_sends_authorization_header(basic_server: str) -> None:
    result = crawl(f"{basic_server}/", headers={"Authorization": BASIC_HEADER}, max_pages=3)
    assert result.pages
    assert result.pages[0].title == "Секретная страница"

    plain = crawl(f"{basic_server}/", max_pages=3)
    assert plain.pages
    assert plain.pages[0].title == ""  # сервер отдал 401-заглушку без title


# --- браузер: настоящий вход на локальном сервере ---


@pytest.mark.browser
def test_scan_without_auth_fails_on_401(basic_server: str) -> None:
    with pytest.raises(ScanError, match="HTTP 401"):
        scan(f"{basic_server}/", allow_private=True, timeout_ms=10_000)


@pytest.mark.browser
def test_scan_basic_auth_opens_page(basic_server: str) -> None:
    result = scan(
        f"{basic_server}/",
        allow_private=True,
        auth=AuthCredentials(kind="basic", login=LOGIN, password=PASSWORD),
    )
    assert result.title == "Секретная страница"


@pytest.mark.browser
def test_scan_site_basic_auth_checks_protected_site(basic_server: str) -> None:
    # без кредов обход не прочитал ни одну страницу — прогон падает, а не «100/100»
    with pytest.raises(ScanError, match="HTTP 401"):
        scan_site(f"{basic_server}/", allow_private=True, timeout_ms=10_000)

    result, crawl_result = scan_site(
        f"{basic_server}/",
        allow_private=True,
        auth=AuthCredentials(kind="basic", login=LOGIN, password=PASSWORD),
    )
    assert result.pages_scanned == 1
    assert result.title == "Секретная страница"
    assert not crawl_result.skipped


@pytest.mark.browser
def test_scan_form_login_enters_password_form(form_server: str) -> None:
    result = scan(
        f"{form_server}/",
        allow_private=True,
        auth=AuthCredentials(kind="form", login=LOGIN, password=PASSWORD),
    )
    assert result.title == "Личный кабинет"


@pytest.mark.browser
def test_scan_form_login_reports_wrong_password(form_server: str) -> None:
    with pytest.raises(ScanError, match="проверьте логин и пароль"):
        scan(
            f"{form_server}/",
            allow_private=True,
            auth=AuthCredentials(kind="form", login=LOGIN, password="wrong"),
            timeout_ms=5_000,
        )


@pytest.mark.browser
def test_scan_form_login_reports_missing_form(form_server: str) -> None:
    with pytest.raises(ScanError, match="нет формы входа"):
        scan(
            f"{form_server}/open",
            allow_private=True,
            auth=AuthCredentials(kind="form", login=LOGIN, password=PASSWORD),
            timeout_ms=5_000,
        )


@pytest.mark.browser
def test_scan_site_form_login_flows_cookies(form_server: str) -> None:
    result, crawl_result = scan_site(
        f"{form_server}/",
        allow_private=True,
        auth=AuthCredentials(kind="form", login=LOGIN, password=PASSWORD),
        timeout_ms=10_000,
    )
    assert result.pages_scanned == 1
    assert result.title == "Личный кабинет"
    assert not crawl_result.skipped
