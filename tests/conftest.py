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
