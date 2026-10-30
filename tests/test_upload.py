"""Загрузка локальной сборки: пути, лимиты, песочница.

Раньше `paths=/tmp/x/index.html` записывался мимо каталога задания, а
загруженный HTML исполнялся на origin приложения — с доступом к cookie и `/api`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from webscope.webapp import app as app_module
from webscope.webapp.app import create_app

# --- загрузка файлов ---


def _upload(client: TestClient, paths: list[str], name: str = "index.html", content: bytes = b"<html></html>"):
    return client.post(
        "/upload",
        files=[("files", (name, content, "text/html")) for _ in paths],
        data={"paths": paths},
    )


def test_upload_rejects_absolute_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_scanner) -> None:
    """Абсолютный путь раньше записывался мимо каталога загрузки."""
    local_dir = tmp_path / "local"
    local_dir.mkdir()
    monkeypatch.setattr(app_module, "_LOCAL_DIR", local_dir)

    app = create_app(db_path=tmp_path / "db.sqlite", scanner_func=stub_scanner, notifier=lambda **kw: [])
    outside = tmp_path / "pwned.txt"
    with TestClient(app) as client:
        response = _upload(client, [str(outside)])
    assert response.status_code == 400
    assert not outside.exists()


def test_upload_keeps_relative_paths_inside(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_scanner) -> None:
    local_dir = tmp_path / "local"
    local_dir.mkdir()
    monkeypatch.setattr(app_module, "_LOCAL_DIR", local_dir)

    app = create_app(db_path=tmp_path / "db.sqlite", scanner_func=stub_scanner, notifier=lambda **kw: [])
    with TestClient(app) as client:
        response = _upload(client, ["../../escape/index.html"])
    assert response.status_code == 200
    written = list(local_dir.rglob("index.html"))
    assert written and local_dir in written[0].parents
    assert not (tmp_path / "escape").exists()


def test_upload_rejects_too_many_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_scanner) -> None:
    local_dir = tmp_path / "local"
    local_dir.mkdir()
    monkeypatch.setattr(app_module, "_LOCAL_DIR", local_dir)
    monkeypatch.setattr(app_module, "MAX_UPLOAD_FILES", 2)

    app = create_app(db_path=tmp_path / "db.sqlite", scanner_func=stub_scanner, notifier=lambda **kw: [])
    with TestClient(app) as client:
        response = _upload(client, ["a.html", "b.html", "c.html"])
    assert response.status_code == 413


def test_upload_rejects_huge_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_scanner) -> None:
    local_dir = tmp_path / "local"
    local_dir.mkdir()
    monkeypatch.setattr(app_module, "_LOCAL_DIR", local_dir)
    monkeypatch.setattr(app_module, "MAX_UPLOAD_FILE_BYTES", 16)

    app = create_app(db_path=tmp_path / "db.sqlite", scanner_func=stub_scanner, notifier=lambda **kw: [])
    with TestClient(app) as client:
        response = _upload(client, ["index.html"], content=b"x" * 100)
    assert response.status_code == 413


def test_uploaded_page_is_served_in_sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_scanner) -> None:
    """Загруженный HTML не должен исполняться с доступом к cookie и API приложения."""
    local_dir = tmp_path / "local"
    local_dir.mkdir()
    monkeypatch.setattr(app_module, "_LOCAL_DIR", local_dir)

    app = create_app(db_path=tmp_path / "db.sqlite", scanner_func=stub_scanner, notifier=lambda **kw: [])
    with TestClient(app) as client:
        response = _upload(client, ["index.html"], content=b"<html><script>fetch('/api/sites')</script></html>")
        assert response.status_code == 200
        page = client.get(response.json()["url"].split("testserver")[-1])
    assert page.status_code == 200
    assert "sandbox" in page.headers["content-security-policy"]
    assert page.headers["x-content-type-options"] == "nosniff"


def test_prune_removes_old_uploads(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    local_dir = tmp_path / "local"
    local_dir.mkdir()
    for index in range(3):
        job = local_dir / f"job{index}"
        job.mkdir()
        (job / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setattr(app_module, "_LOCAL_DIR", local_dir)
    app_module._prune_local_uploads(keep=2)
    assert len(list(local_dir.iterdir())) == 2
