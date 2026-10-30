"""Лимиты запуска проверок: один клиент не должен занять весь сервер."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from webscope.webapp.app import create_app

# --- лимиты ---


def test_rate_limit_stops_scan_loop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_scanner) -> None:
    monkeypatch.setenv("WEBSCOPE_RATE_LIMIT", "2")
    monkeypatch.delenv("WEBSCOPE_AUTH_PASSWORD", raising=False)
    app = create_app(db_path=tmp_path / "db.sqlite", scanner_func=stub_scanner, notifier=lambda **kwargs: [])
    with TestClient(app) as client:
        statuses = [
            client.post("/sites", data={"url": f"example{index}.com"}, follow_redirects=False).status_code
            for index in range(3)
        ]
    assert statuses[:2] == [303, 303]
    assert statuses[2] == 429


def test_max_concurrent_scans_returns_429(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_scanner) -> None:
    monkeypatch.setenv("WEBSCOPE_MAX_CONCURRENT_SCANS", "1")
    monkeypatch.delenv("WEBSCOPE_AUTH_PASSWORD", raising=False)
    app = create_app(db_path=tmp_path / "db.sqlite", scanner_func=stub_scanner, notifier=lambda **kw: [])
    storage = app.state.storage
    site = storage.add_site("https://example.com/")
    storage.start_run(site.id)  # имитируем идущий прогон

    with TestClient(app) as client:
        response = client.post(f"/api/sites/{site.id}/scan")
    assert response.status_code == 429
    assert "максимум" in response.json()["detail"]
