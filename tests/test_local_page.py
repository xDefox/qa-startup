"""Живой прогон сканера по локальной странице: дефекты находятся и не дублируются.

Локальная страница раздаётся из теста (127.0.0.1) — без интернета. Так проверяем
сквозной путь scanner → checks → scoring → отчёт, а не отдельные модули.
"""

from __future__ import annotations

import socket
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from webscope.models import Severity
from webscope.scanner import scan

HTML = """<!doctype html>
<html>
<head>
<style>body{margin:0;font:16px sans-serif} .ov{position:fixed;left:0;top:0;width:300px;height:300px;background:rgba(0,0,0,.6);z-index:5}
#btn{position:fixed;left:40px;top:40px;z-index:1}</style>
</head>
<body>
<a id="btn" href="#x">Кнопка</a>
<div class="ov"></div>
<a href="/x"><img src="/logo.png" alt="Логотип"></a>
<a href="/y"></a>
<iframe src="/frame.html"></iframe>
<input type="text">
</body>
</html>
"""


@pytest.fixture()
def local_site(tmp_path: Path):
    (tmp_path / "index.html").write_text(HTML, encoding="utf-8")
    (tmp_path / "frame.html").write_text("<!doctype html><html lang='ru'><title>frame</title><h1>f</h1></html>", encoding="utf-8")
    handler = partial(SimpleHTTPRequestHandler, directory=str(tmp_path))
    handler.log_message = lambda *args, **kwargs: None  # type: ignore[method-assign]
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}/index.html"
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.browser
def test_scan_local_page_finds_defects_once(local_site: str) -> None:
    result = scan(local_site, allow_private=True)
    rules = [finding.rule for finding in result.findings]

    # Если iframe без title: одна находка, не две (axe frame-title + наша).
    assert rules.count("content/frame-title") == 1, rules
    assert "frame-title" not in rules, f"дубль axe frame-title: {rules}"

    # Ссылка с img alt — имя есть; пустая ссылка — находка.
    empty_links = [f for f in result.findings if f.rule == "content/empty-link-name"]
    assert len(empty_links) == 1, [f.snippet for f in empty_links]
    assert empty_links[0].details.get("href") == "/y"

    # <a><img без alt></a> — один дефект ссылки, а не три (link-name + image-alt
    # + наша находка): axe-дубли убраны при наличии своего правила.
    no_alt = [f for f in result.findings if f.rule in ("link-name", "image-alt")]
    assert no_alt == [], [f.rule for f in no_alt]

    # Настоящее перекрытие кнопки находится как critical.
    blockers = [f for f in result.findings if f.rule == "interaction/button-blocked"]
    assert blockers and blockers[0].severity is Severity.CRITICAL

    # Ошибки сторонних доменов отсутствуют, счётчик external пуст.
    assert result.summary["external"] == 0
    # Балл не 100 из-за перекрытия и пустой ссылки.
    assert result.score < 100
