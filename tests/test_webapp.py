"""Тесты веб-слоя: хранилище, монитор, маршруты."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from webscope.models import Finding, ScanResult, Severity
from webscope.webapp.alerts import build_alert_text
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
        help_url="https://www.w3.org/WAI/WCAG22/Understanding/non-text-content.html",
        source="webscope.content",
        details={"evidence": "001_content_image_alt.png"},
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


def test_monitor_notifies_about_worsened_severity(tmp_path: Path) -> None:
    """Новых находок нет, но старая стала серьёзнее — алерт всё равно уходит."""
    storage = Storage(tmp_path / "db.sqlite")
    site = storage.add_site("https://site.com/")
    sent: list[str] = []

    def notifier(**kwargs):
        diff = kwargs["diff"]
        sent.append(f"{len(diff.new_findings)} new / {len(diff.worsened_findings)} worsened")
        return ["email"]

    monitor = Monitor(
        storage,
        ScanOptions(),
        scanner_func=lambda url, options: CrawlOutcome(_result([_finding(severity=Severity.MODERATE)])),
        notifier=notifier,
    )
    monitor.run_site(site)
    assert sent == []  # первый прогон — сравнивать не с чем

    # та же находка, но серьёзнее (moderate → critical): новых нет, стало хуже
    worsened = Monitor(
        storage,
        ScanOptions(),
        scanner_func=lambda url, options: CrawlOutcome(_result([_finding(severity=Severity.CRITICAL)])),
        notifier=notifier,
    )
    worsened.run_site(site)
    assert sent == ["0 new / 1 worsened"]
    storage.close()


def test_alert_text_mentions_worsened_findings() -> None:
    """Алерт рассказывает не только о новых, но и об ухудшившихся проблемах."""
    from webscope.history import DiffEntry, DiffReport

    diff = DiffReport(
        url="https://site.com/",
        score_before=90,
        score_after=60,
        changed_findings=[
            DiffEntry(
                kind="changed",
                rule="a11y/color-contrast",
                title="Низкий контраст текста",
                url="https://site.com/",
                severity_before="moderate",
                severity_after="critical",
            )
        ],
    )
    text = build_alert_text("https://site.com/", diff)
    assert "Ухудшилось" in text
    assert "moderate → critical" in text


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


# --- кабинет управления ---


def test_settings_page_shows_current_values(client: TestClient) -> None:
    site_id = _create_site(client)
    storage: Storage = client.app.state.storage
    storage.update_site(site_id, email="owner@example.com", schedule="weekly")

    response = client.get(f"/sites/{site_id}/settings")
    assert response.status_code == 200
    assert "owner@example.com" in response.text
    assert 'value="weekly" selected' in response.text


def test_settings_save_updates_site(client: TestClient) -> None:
    site_id = _create_site(client)
    storage: Storage = client.app.state.storage

    response = client.post(
        f"/sites/{site_id}/settings",
        data={"email": " new@example.com ", "telegram_chat": "-100123", "schedule": "daily"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "saved=1" in response.headers["location"]

    site = storage.get_site(site_id)
    assert site.email == "new@example.com"  # пробелы обрезаны
    assert site.telegram_chat == "-100123"
    assert site.schedule == "daily"
    assert site.next_run_at is not None  # дата следующего запуска пересчитана


def test_settings_clear_email(client: TestClient) -> None:
    site_id = _create_site(client)
    storage: Storage = client.app.state.storage
    storage.update_site(site_id, email="owner@example.com")

    client.post(f"/sites/{site_id}/settings", data={"email": "", "schedule": "off"})
    assert storage.get_site(site_id).email is None


def test_delete_site_removes_history(client: TestClient) -> None:
    site_id = _create_site(client)
    storage: Storage = client.app.state.storage
    run = storage.start_run(site_id)
    storage.finish_run(run.id, _result([_finding()]))

    response = client.post(f"/sites/{site_id}/delete", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert storage.get_site(site_id) is None
    assert storage.findings_of(run.id) == []  # каскад унёс прогоны и находки


def test_settings_unknown_site_404(client: TestClient) -> None:
    assert client.get("/sites/999/settings").status_code == 404
    assert client.post("/sites/999/delete").status_code == 404


def test_normalize_url() -> None:
    assert normalize_url("example.com") == "https://example.com"
    assert normalize_url("http://example.com/x") == "http://example.com/x"
    # локальные стенды и загруженные файлы проверяются через localhost
    assert normalize_url("localhost") == "https://localhost"
    assert normalize_url("localhost:8888/a.html") == "https://localhost:8888/a.html"
    with pytest.raises(ValueError):
        normalize_url("")
    with pytest.raises(ValueError):
        normalize_url("это не адрес")


# --- миграция и новые колонки находок ---


_OLD_SCHEMA = """
CREATE TABLE sites (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    url             TEXT NOT NULL UNIQUE,
    email           TEXT,
    telegram_chat   TEXT,
    schedule        TEXT NOT NULL DEFAULT 'off',
    interval_days   INTEGER NOT NULL DEFAULT 7,
    next_run_at     TEXT,
    created_at      TEXT NOT NULL
);
CREATE TABLE runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id       INTEGER NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    status        TEXT NOT NULL DEFAULT 'running',
    score         INTEGER,
    pages_scanned INTEGER NOT NULL DEFAULT 0,
    duration_ms   INTEGER NOT NULL DEFAULT 0,
    error         TEXT,
    raw           TEXT
);
CREATE TABLE findings (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id    INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    rule      TEXT NOT NULL,
    severity  TEXT NOT NULL,
    title     TEXT,
    message   TEXT,
    url       TEXT,
    selector  TEXT,
    snippet   TEXT
);
"""


def test_storage_migrates_old_schema(tmp_path: Path) -> None:
    """Старая БД без колонок source/help_url/details дозаполняется и продолжает работать."""
    db = tmp_path / "old.sqlite"
    connection = sqlite3.connect(db)
    connection.executescript(_OLD_SCHEMA)
    connection.execute("INSERT INTO sites (url, created_at) VALUES ('https://site.com/', '2026-10-01T00:00:00+00:00')")
    connection.execute(
        "INSERT INTO runs (site_id, started_at, status, score) VALUES (1, '2026-10-01T00:00:00+00:00', 'ok', 92)"
    )
    connection.execute(
        "INSERT INTO findings (run_id, rule, severity, title) VALUES (1, 'content/image-alt', 'serious', 'Изображение без alt')"
    )
    connection.commit()
    connection.close()

    storage = Storage(db)
    # старая находка читается, новые колонки пустые
    legacy = storage.findings_of(1)
    assert len(legacy) == 1
    assert legacy[0].details == {}
    assert legacy[0].help_url is None

    # новые прогоны пишут и читают новые колонки
    run = storage.start_run(1)
    storage.finish_run(run.id, _result([_finding()]))
    stored = storage.findings_as_models(run.id)
    assert stored[0].help_url == "https://www.w3.org/WAI/WCAG22/Understanding/non-text-content.html"
    assert stored[0].source == "webscope.content"
    assert stored[0].details == {"evidence": "001_content_image_alt.png"}
    storage.close()


# --- загрузка локальных файлов ---


def test_upload_uses_request_host(tmp_path: Path) -> None:
    """Адрес залитых файлов строится по host:port запроса, а не из env."""
    app = create_app(
        db_path=tmp_path / "db.sqlite",
        scanner_func=lambda url, options: CrawlOutcome(_result([])),
        notifier=lambda **kwargs: [],
    )
    with TestClient(app) as client:
        response = client.post(
            "/upload",
            files=[("files", ("index.html", b"<html><title>x</title></html>", "text/html"))],
            data={"paths": "index.html"},
        )
        assert response.status_code == 200
        assert response.json()["url"].startswith("http://testserver/__local/")


def test_local_upload_scan_allows_private(tmp_path: Path) -> None:
    """Loopback разрешён только для своих загруженных файлов (/__local/), чужие адреса — нет."""
    captured: list[ScanOptions] = []

    def scanner(url: str, options: ScanOptions) -> CrawlOutcome:
        captured.append(options)
        return CrawlOutcome(_result([]))

    app = create_app(db_path=tmp_path / "db.sqlite", scanner_func=scanner, notifier=lambda **kwargs: [])
    monitor: Monitor = app.state.monitor

    monitor.scanner_func("http://127.0.0.1:8000/__local/abc/index.html", ScanOptions())
    monitor.scanner_func("http://127.0.0.1:9200/", ScanOptions())
    assert captured[0].allow_private is True
    assert captured[1].allow_private is False


# --- шапка сайта ---


def test_site_page_crosses_out_previous_score(client: TestClient) -> None:
    site_id = _create_site(client)
    storage: Storage = client.app.state.storage

    first = storage.start_run(site_id)
    storage.finish_run(first.id, _result([_finding()]))  # 92
    second = storage.start_run(site_id)
    storage.finish_run(second.id, _result([_finding(severity=Severity.CRITICAL)]))  # ниже

    response = client.get(f"/sites/{site_id}")
    assert response.status_code == 200
    assert 'class="score-prev"' in response.text
    assert "92" in response.text  # прошлый балл виден «заклеенным»


def test_site_page_links_to_help(client: TestClient) -> None:
    site_id = _create_site(client)
    storage: Storage = client.app.state.storage
    run = storage.start_run(site_id)
    storage.finish_run(run.id, _result([_finding()]))

    response = client.get(f"/sites/{site_id}")
    assert "Подробнее о проверке" in response.text
    assert "w3.org" in response.text


def test_report_survives_long_failure_streak(tmp_path: Path) -> None:
    """Отчёт не должен исчезать после череды неудачных прогонов.

    Регресс: latest_ok_run смотрел только последние 20 строк, и после
    20 упавших проверок интерфейс показывал «отчёт ещё не готов».
    """
    storage = Storage(tmp_path / "db.sqlite")
    site = storage.add_site("https://site.com/")
    good = storage.start_run(site.id)
    storage.finish_run(good.id, _result([_finding()]))
    for _ in range(25):
        failed = storage.start_run(site.id)
        storage.fail_run(failed.id, "сайт недоступен")

    assert storage.latest_ok_run(site.id) is not None
    assert storage.latest_ok_run(site.id).id == good.id
    storage.close()


# --- нормализация адреса ---


def test_normalize_url_rejects_header_injection() -> None:
    with pytest.raises(ValueError):
        normalize_url("evil.com\nBcc: victim@example.com")


def test_normalize_url_rejects_credentials() -> None:
    with pytest.raises(ValueError):
        normalize_url("http://user:pass@127.0.0.1/")


def test_normalize_url_rejects_invalid_port() -> None:
    with pytest.raises(ValueError):
        normalize_url("a.b:99999")


def test_normalize_url_accepts_ipv6() -> None:
    assert normalize_url("[::1]") == "https://[::1]"


def test_normalize_url_keeps_local_sites() -> None:
    assert normalize_url("localhost:8888/a.html") == "https://localhost:8888/a.html"
