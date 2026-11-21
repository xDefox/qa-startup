"""Общие фикстуры: локальный HTTP-стенд и заглушка сканера.

Стенд нужен сетевым проверкам (SSRF, краулер), а заглушка сканера — тестам
веб-слоя: им не нужен настоящий Playwright, только «прогон без находок».
"""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import ClassVar

import pytest


class _Handler(BaseHTTPRequestHandler):
    pages: ClassVar[dict[str, str]] = {
        "/": "<html><head><title>Главная</title></head><body><a href='/a/1'>1</a></body></html>",
        "/a/1": "<html><head><title>Товар первый</title></head><body>ok</body></html>",
        "/a/2": "<html><head><title>Товар второй</title></head><body>ok</body></html>",
        "/sitemap.xml": (
            "<?xml version='1.0'?><urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'>"
            "<url><loc>http://127.0.0.1:{port}/a/1</loc></url>"
            "<url><loc>http://127.0.0.1:{port}/a/2</loc></url></urlset>"
        ),
        "/robots.txt": "User-agent: *\nAllow: /\n",
    }

    def do_GET(self):
        body = self.pages.get(self.path)
        if body is None:
            self.send_response(404)
            self.end_headers()
            return
        body = body.replace("{port}", str(self.server.server_address[1]))
        payload = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        return


@pytest.fixture
def local_site() -> str:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def stub_scanner():
    """Сканер-заглушка: пустой прогон, без запуска браузера."""
    from webscope.models import ScanResult
    from webscope.webapp.scheduler import CrawlOutcome

    def _scan(url: str, options) -> CrawlOutcome:
        return CrawlOutcome(ScanResult(url=url, final_url=url))

    return _scan


DEFAULT_TEST_EMAIL = "tester@example.com"
DEFAULT_TEST_PASSWORD = "test-password-123"


def sign_in(
    client,
    email: str = DEFAULT_TEST_EMAIL,
    password: str = DEFAULT_TEST_PASSWORD,
    *,
    register: bool = True,
):
    """Регистрирует тестового пользователя и оставляет его залогиненным.

    Кабинет закрыт по умолчанию, поэтому почти каждому тесту веб-слоя нужен
    реальный пользователь. Если аккаунт уже есть — просто входит.
    """
    if register:
        response = client.post(
            "/auth/register",
            data={"email": email, "password": password, "password_confirm": password},
            follow_redirects=False,
        )
        assert response.status_code == 303, response.text
        return response
    response = client.post(
        "/auth/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    return response
