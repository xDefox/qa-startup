"""robots.txt для одиночного `scan`.

Обход сайта (`crawl`) robots.txt уважал всегда, а `webscope scan` — нет:
движок противоречил сам себе, и одиночная проверка проходила по странице,
которую владелец закрыл от роботов.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from webscope.scanner import robots_block_reason, scan

UA = "webscope-test/1.0 (+https://example.com)"
PAGE = b"<html><head><title>Page</title></head><body>ok</body></html>"


@contextmanager
def _serve(robots: str | None = None, status: int = 200, required_auth: str | None = None):
    """Поднимает локальный стенд с заданным robots.txt."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if required_auth is not None and self.headers.get("Authorization") != required_auth:
                # закрытый стенд: без учётных данных сервер отвечает 403
                self.send_response(403)
                self.end_headers()
                return
            if self.path == "/robots.txt":
                if robots is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                payload = robots.encode("utf-8")
                self.send_response(status)
            else:
                payload = PAGE
                self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def test_robots_allows_open_page() -> None:
    with _serve("User-agent: *\nDisallow: /private\n") as site:
        assert robots_block_reason(f"{site}/page", allow_private=True, user_agent=UA) is None


def test_robots_blocks_closed_page() -> None:
    with _serve("User-agent: *\nDisallow: /private\n") as site:
        reason = robots_block_reason(f"{site}/private", allow_private=True, user_agent=UA)
    assert reason is not None
    assert "robots.txt" in reason
    assert "--ignore-robots" in reason, "пользователь должен понимать, как обойти запрет"


def test_missing_robots_means_allowed() -> None:
    """404 на robots.txt — это «файла нет», а не «всё запрещено»."""
    with _serve(None) as site:
        assert robots_block_reason(f"{site}/private", allow_private=True, user_agent=UA) is None


def test_robots_403_forbids_everything() -> None:
    """RFC 9309: 403 на robots.txt — роботу отказано в доступе."""
    with _serve("User-agent: *\nAllow: /\n", status=403) as site:
        reason = robots_block_reason(f"{site}/page", allow_private=True, user_agent=UA)
    assert reason is not None


def test_scan_respects_robots_by_default() -> None:
    import inspect

    parameters = inspect.signature(scan).parameters
    assert parameters["respect_robots"].default is True


def test_robots_is_asked_with_auth_headers() -> None:
    """Закрытый стенд: robots.txt с 403 без авторизации не должен блокировать свой же скан."""
    header = "Basic dXNlcjpwYXNz"
    with _serve("User-agent: *\nAllow: /\n", required_auth=header) as site:
        blocked = robots_block_reason(f"{site}/page", allow_private=True, user_agent=UA)
        allowed = robots_block_reason(
            f"{site}/page", allow_private=True, user_agent=UA, headers={"Authorization": header}
        )
    assert blocked is not None, "без авторизации сервер отвечает 403 — robots закрыт"
    assert allowed is None, "с авторизацией robots.txt отдаётся и разрешает обход"
