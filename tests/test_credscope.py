"""Утечка кредов: Authorization и Cookie живут только на хостах сайта.

Регресс-тесты на четыре канала из 4-стороннего ревью: basic-заголовок на
все запросы браузерного контекста, плоская cookie-строка для httpx и
авторизация на чужие sitemap-хосты.
"""

from __future__ import annotations

import base64
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from socket import socket
from typing import ClassVar

import httpx

from webscope.crawler import crawl
from webscope.credscope import auth_origins, in_scope, scoped_cookie_header, strip_out_of_scope_headers

BASIC = "Basic " + base64.b64encode(b"user:pass").decode()


# --- скоуп хоста ---


def test_in_scope_roots_subdomains_and_parent_domain() -> None:
    root = "https://student.vstu.by/lk/"
    assert in_scope("student.vstu.by", root)  # сам корень
    assert in_scope("www.student.vstu.by", root)  # поддомен корня
    assert in_scope("vstu.by", root)  # родитель: apex↔www редиректы
    assert in_scope("STUDENT.VSTU.BY", root)  # регистр не важен

    assert not in_scope("auth.vstu.by", root)  # чужой поддомен родителя
    assert not in_scope("by", root)  # TLD доменом не считаем
    assert not in_scope("vstu-by.example.com", root)  # похожее имя — не хост
    assert not in_scope("example.com", root)
    assert not in_scope(None, root)
    assert not in_scope("", root)


def test_in_scope_single_label_root() -> None:
    root = "http://intranet/"
    assert in_scope("intranet", root)
    assert in_scope("static.intranet", root)
    assert not in_scope("intranet.evil.com", root)


def test_auth_origins_cover_www_twin_and_ports() -> None:
    assert auth_origins("https://site.by/page") == ["https://site.by", "https://www.site.by"]
    assert auth_origins("https://www.site.by/") == ["https://www.site.by", "https://site.by"]
    # порт по умолчанию не пишем (браузер нормализует origin), явный — пишем
    assert auth_origins("https://site.by:8443/") == ["https://site.by:8443", "https://www.site.by:8443"]
    # IP-адресу двойника не придумываем
    assert auth_origins("http://127.0.0.1:8080/") == ["http://127.0.0.1:8080"]
    assert auth_origins("ftp://site.by/") == []


# --- cookie-строка для краулера ---


def test_cookie_header_keeps_only_own_domains() -> None:
    cookies = [
        {"name": "session", "value": "abc", "domain": ".vstu.by"},
        {"name": "lk", "value": "1", "domain": "student.vstu.by"},
        {"name": "sso", "value": "ticket", "domain": "auth.vstu.by"},  # браузер не шлёт её основному хосту
        {"name": "ga", "value": "GA1.2", "domain": ".intercom.io"},  # кука третьей стороны из сессии входа
    ]
    assert scoped_cookie_header(cookies, "https://student.vstu.by/") == "session=abc; lk=1"
    assert scoped_cookie_header([], "https://site.by/") is None


# --- httpx hook ---


def test_hook_strips_creds_from_foreign_hosts_only() -> None:
    hook = strip_out_of_scope_headers("https://student.vstu.by/")

    foreign = httpx.Request(
        "GET",
        "https://cdn.shop.com/sitemap.xml",
        headers={"Authorization": BASIC, "Cookie": "s=1", "User-Agent": "ua"},
    )
    hook(foreign)
    assert "authorization" not in foreign.headers
    assert "cookie" not in foreign.headers
    assert foreign.headers["user-agent"] == "ua"  # чужих заголовков не трогаем

    own = httpx.Request("GET", "https://www.student.vstu.by/x", headers={"Authorization": BASIC})
    hook(own)
    assert own.headers["authorization"] == BASIC


# --- интеграция: живой краулер, два хоста ---


def _serve(handler_class: type[BaseHTTPRequestHandler], hostname: str = "127.0.0.1"):
    """HTTP-сервер на loopback со свободным портом.

    ``hostname`` — как к нему обращаться в URL: сквоуп кредов считается по
    hostname (куки игнорируют порты), поэтому «чужой хост» в тестах — это
    localhost против 127.0.0.1, а не другой порт.
    """
    with socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = ThreadingHTTPServer(("127.0.0.1", port), handler_class)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"{hostname}:{port}"


class _Recorder(BaseHTTPRequestHandler):
    """Чужой хост: записывает увиденные заголовки и отвечает 200 с пустым sitemap."""

    seen: ClassVar[list[dict]] = []

    def do_GET(self) -> None:
        type(self).seen.append(
            {
                "path": self.path,
                "authorization": self.headers.get("Authorization"),
                "cookie": self.headers.get("Cookie"),
            }
        )
        payload = b"<?xml version='1.0'?><urlset></urlset>"
        self.send_response(200)
        self.send_header("Content-Type", "application/xml")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args) -> None:
        """Тишина в тестах."""


class _SiteHandler(BaseHTTPRequestHandler):
    """Сайт за basic-кодом: sitemap-индекс и homepage ссылаются на чужой хост."""

    foreign_url = ""

    def do_GET(self) -> None:
        if self.headers.get("Authorization") != BASIC:
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="t"')
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self.path.startswith("/sitemap.xml"):
            payload = (
                "<?xml version='1.0'?><sitemapindex>"
                f"<sitemap><loc>http://{self.foreign_url}/child.xml</loc></sitemap>"
                "</sitemapindex>"
            ).encode()
        else:
            payload = (
                "<html><head><title>Сайт</title>"
                f'<link rel="sitemap" href="http://{self.foreign_url}/foreign-sitemap.xml">'
                "</head><body><p>ok</p></body></html>"
            ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args) -> None:
        """Тишина в тестах."""


def test_crawl_does_not_send_creds_to_foreign_sitemap_hosts() -> None:
    """Канал утечки: sitemap-индекс и ссылки на sitemap с чужих хостов.

    Краулер шлёт один клиент на всё — раньше Authorization и Cookie уходили
    и на чужие sitemap-хосты, которые сайт лишь упомянул.
    """
    _Recorder.seen = []
    # чужой хост — другой hostname (127.0.0.1 против localhost): порт сам
    # по себе скоуп не меняет, куки игнорируют порты
    foreign_server, foreign_url = _serve(_Recorder, hostname="localhost")
    _SiteHandler.foreign_url = foreign_url
    site_server, site_url = _serve(_SiteHandler)
    try:
        result = crawl(
            f"http://{site_url}/",
            headers={"Authorization": BASIC, "Cookie": "session=abc"},
            max_pages=3,
            respect_robots=False,
            allow_private=True,
        )
    finally:
        site_server.shutdown()
        site_server.server_close()
        foreign_server.shutdown()
        foreign_server.server_close()

    # канал действительно отработан: чужой хост запрашивали и по sitemap-индексу, и по ссылке
    paths = {item["path"] for item in _Recorder.seen}
    assert "/child.xml" in paths
    assert "/foreign-sitemap.xml" in paths
    # но секретов не увидел ни разу
    for request in _Recorder.seen:
        assert request["authorization"] is None, f"чужой хост увидел Authorization: {request}"
        assert request["cookie"] is None, f"чужой хост увидел Cookie: {request}"
    # и при этом сам сайт авторизован — краулер дошёл до него
    assert result.pages and result.pages[0].title == "Сайт"
