"""Тесты веб-слоя: хранилище, монитор, маршруты."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from webscope.models import Finding, ScanResult, Severity
from webscope.webapp.app import create_app, normalize_url
from webscope.webapp.scheduler import CrawlOutcome, Monitor, ScanOptions
from webscope.webapp.storage import Storage


def _finding(rule: str = "content/image-alt", severity: Severity = Severity.SERIOUS) -> Finding:
    return Finding(
        rule=rule,
        severity=severity,
        title="Изображение без alt",
        message="У <img> нет атрибута alt",
        url="https://site.com/",
        selector="main > img",
        snippet="<img src='/logo.png'>",
    )


def _result(findings: list[Finding] | None = None) -> ScanResult:
    result = ScanResult(url="https://site.com/", final_url="https://site.com/", title="Сайт")
    result.findings = list(findings or [])
    result.pages_scanned = 1
    return result


# --- хранилище ---


def test_add_site_is_idempotent(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "db.sqlite")
    first = storage.add_site("https://site.com/")
    second = storage.add_site("https://site.com/")
    assert first.id == second.id
    assert len(storage.list_sites()) == 1
    storage.close()


def test_finish_run_stores_findings(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "db.sqlite")
    site = storage.add_site("https://site.com/")
    run = storage.start_run(site.id)
    stored = storage.finish_run(run.id, _result([_finding()]))

    assert stored.status == "ok"
    assert stored.score == 92
    findings = storage.findings_as_models(run.id)
    assert len(findings) == 1
    assert findings[0].severity is Severity.SERIOUS
    assert findings[0].rule == "content/image-alt"
    storage.close()


def test_diff_with_previous_detects_new_finding(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "db.sqlite")
    site = storage.add_site("https://site.com/")

    first = storage.start_run(site.id)
    storage.finish_run(first.id, _result([]))

    second = storage.start_run(site.id)
    storage.finish_run(second.id, _result([_finding()]))

    diff = storage.diff_with_previous(second)
    assert diff is not None
    assert [entry.rule for entry in diff.new_findings] == ["content/image-alt"]
    assert diff.score_after < diff.score_before
    storage.close()


def test_severity_counts(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "db.sqlite")
    site = storage.add_site("https://site.com/")
    run = storage.start_run(site.id)
    storage.finish_run(run.id, _result([_finding(), _finding("content/missing-title", Severity.MODERATE)]))
    counts = storage.severity_counts([run.id])
    assert counts[run.id]["serious"] == 1
    assert counts[run.id]["moderate"] == 1
    storage.close()


def test_due_sites_respects_schedule(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "db.sqlite")
    site = storage.add_site("https://site.com/", schedule="weekly")
    storage.update_site(site.id, next_run_at=(datetime.now(UTC) - timedelta(hours=1)).isoformat())
    assert [item.id for item in storage.due_sites()] == [site.id]

    storage.update_site(site.id, next_run_at=(datetime.now(UTC) + timedelta(days=3)).isoformat())
    assert storage.due_sites() == []
    storage.close()


# --- монитор ---


def test_monitor_runs_scan_and_saves_result(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "db.sqlite")
    site = storage.add_site("https://site.com/")
    monitor = Monitor(storage, ScanOptions(), scanner_func=lambda url, options: CrawlOutcome(_result([_finding()])))

    run = monitor.run_site(site)
    assert run.status == "ok"
    assert run.score == 92
    assert len(storage.findings_of(run.id)) == 1
    storage.close()


def test_monitor_notifies_only_about_new_findings(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "db.sqlite")
    site = storage.add_site("https://site.com/")
    sent: list[str] = []

    def notifier(**kwargs):
        sent.append(kwargs["site_url"])
        return ["email"]

    monitor = Monitor(
        storage,
        ScanOptions(),
        scanner_func=lambda url, options: CrawlOutcome(_result([_finding()])),
        notifier=notifier,
    )

    monitor.run_site(site)  # первый прогон — сравнивать не с чем
    assert sent == []

    monitor.run_site(site)  # тот же результат — новых проблем нет
    assert sent == []

    storage.close()


def test_monitor_records_failure(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "db.sqlite")
    site = storage.add_site("https://site.com/")

    def boom(url, options):
        raise RuntimeError("сайт недоступен")

    monitor = Monitor(storage, ScanOptions(), scanner_func=boom)
    run = monitor.run_site(site)
    assert run.status == "error"
    assert "недоступен" in (run.error or "")
    storage.close()


# --- маршруты ---


@pytest.fixture
def client(tmp_path: Path):
    app = create_app(
        db_path=tmp_path / "db.sqlite",
        scanner_func=lambda url, options: CrawlOutcome(_result([_finding()])),
        notifier=lambda **kwargs: [],
    )
    with TestClient(app) as test_client:
        yield test_client


def test_healthz(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_index_contains_form(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "Проверьте свой сайт" in response.text
    assert 'name="url"' in response.text


def test_create_site_redirects(client: TestClient) -> None:
    response = client.post("/sites", data={"url": "example.com", "schedule": "off"}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/sites/")


def _create_site(client: TestClient, url: str = "example.com") -> int:
    """Создаёт сайт и возвращает его id (редирект не разворачиваем)."""
    response = client.post("/sites", data={"url": url}, follow_redirects=False)
    return int(response.headers["location"].rstrip("/").split("/")[-1])


def test_create_site_rejects_garbage(client: TestClient) -> None:
    response = client.post("/sites", data={"url": "не-сайт"})
    assert response.status_code == 400
    assert "адрес" in response.text.lower()


def test_site_page_shows_report(client: TestClient) -> None:
    site_id = _create_site(client)
    storage: Storage = client.app.state.storage

    run = storage.start_run(site_id)
    storage.finish_run(run.id, _result([_finding()]))

    response = client.get(f"/sites/{site_id}")
    assert response.status_code == 200
    assert "92" in response.text
    assert "Что сделать" in response.text


def test_api_returns_findings(client: TestClient) -> None:
    site_id = _create_site(client)
    storage: Storage = client.app.state.storage
    run = storage.start_run(site_id)
    storage.finish_run(run.id, _result([_finding()]))

    response = client.get(f"/api/sites/{site_id}")
    assert response.status_code == 200
    payload = response.json()
    assert payload["last_run"]["status"] == "ok"
    assert payload["findings"][0]["rule"] == "content/image-alt"


def test_site_page_keeps_previous_report_after_failure(client: TestClient) -> None:
    site_id = _create_site(client)
    storage: Storage = client.app.state.storage

    run = storage.start_run(site_id)
    storage.finish_run(run.id, _result([_finding()]))
    failed = storage.start_run(site_id)
    storage.fail_run(failed.id, "сайт недоступен")

    response = client.get(f"/sites/{site_id}")
    assert response.status_code == 200
    assert "92" in response.text
    assert "не удалась" in response.text


def test_history_page(client: TestClient) -> None:
    site_id = _create_site(client)
    storage: Storage = client.app.state.storage
    run = storage.start_run(site_id)
    storage.finish_run(run.id, _result([_finding()]))

    response = client.get(f"/sites/{site_id}/history")
    assert response.status_code == 200
    assert "История проверок" in response.text


def test_normalize_url() -> None:
    assert normalize_url("example.com") == "https://example.com"
    assert normalize_url("http://example.com/x") == "http://example.com/x"
    with pytest.raises(ValueError):
        normalize_url("")
    with pytest.raises(ValueError):
        normalize_url("localhost")
