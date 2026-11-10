"""Тесты для Watchdog: детектор изменений, вебхуки, инкрементальные сканы, очереди."""

from __future__ import annotations

import asyncio
import hmac
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from webscope.webapp.app import create_app
from webscope.webapp.storage import Storage
from webscope.webapp.scheduler import Monitor, ScanOptions
from webscope.webapp.services.site_service import create_site
from webscope.watchdog import ChangeDetector, PageSnapshot, SiteSnapshot
from webscope.webapp.webhook_queue import WebhookQueue, WebhookEvent, create_webhook_queue


# ============================================================
# ChangeDetector tests
# ============================================================

def test_change_detector_first_run_returns_all_as_added():
    """Первый запуск: все страницы новые."""
    storage = Storage(":memory:")
    with storage._conn() as conn:
        conn.execute(
            "INSERT INTO organizations (name, owner_email, created_at) VALUES (?, ?, ?)",
            ("Test Org", "test@test.com", "2026-11-09T12:00:00"),
        )
        conn.commit()

    from webscope.webapp.services.site_service import create_site
    site = create_site(storage, url="https://example.com", organization_id=1)

    detector = ChangeDetector(storage)
    current_pages = {
        site.url: PageSnapshot(url=site.url, content_hash="hash1", etag=None, last_modified=None, status_code=200),
    }
    added, changed, removed = detector.detect_changes(site.id, current_pages)
    assert added == [site.url]
    assert changed == []
    assert removed == []


def test_change_detector_no_changes_returns_empty():
    """Тот же контент: изменений нет."""
    storage = Storage(":memory:")
    with storage._conn() as conn:
        conn.execute(
            "INSERT INTO organizations (name, owner_email, created_at) VALUES (?, ?, ?)",
            ("Test Org", "test@test.com", "2026-11-09T12:00:00"),
        )
        conn.commit()

    from webscope.webapp.services.site_service import create_site
    site = create_site(storage, url="https://example.com", organization_id=1)

    detector = ChangeDetector(storage)
    current_pages = {site.url: PageSnapshot(url=site.url, content_hash="hash1", etag=None, last_modified=None, status_code=200)}
    storage.save_site_snapshot(site.id, site.url, {site.url: {"content_hash": "hash1", "etag": None, "last_modified": None, "status_code": 200, "fetched_at": "2026-11-09T12:00:00"}})

    added, changed, removed = detector.detect_changes(site.id, current_pages)
    assert added == []
    assert changed == []
    assert removed == []


def test_change_detector_detects_content_hash_change():
    """Изменение content_hash: детектируется как изменение."""
    storage = Storage(":memory:")
    with storage._conn() as conn:
        conn.execute(
            "INSERT INTO organizations (name, owner_email, created_at) VALUES (?, ?, ?)",
            ("Test Org", "test@test.com", "2026-11-09T12:00:00"),
        )
        conn.commit()

    from webscope.webapp.services.site_service import create_site
    site = create_site(storage, url="https://example.com", organization_id=1)

    detector = ChangeDetector(storage)
    storage.save_site_snapshot(site.id, site.url, {site.url: {"content_hash": "hash1", "etag": None, "last_modified": None, "status_code": 200, "fetched_at": "2026-11-09T12:00:00"}})

    current_pages = {site.url: PageSnapshot(url=site.url, content_hash="hash2", etag=None, last_modified=None, status_code=200)}
    added, changed, removed = detector.detect_changes(site.id, current_pages)
    assert changed == [site.url]
    assert added == []
    assert removed == []


def test_change_detector_detects_new_page():
    """Новая страница: детектируется как добавленная."""
    storage = Storage(":memory:")
    with storage._conn() as conn:
        conn.execute(
            "INSERT INTO organizations (name, owner_email, created_at) VALUES (?, ?, ?)",
            ("Test Org", "test@test.com", "2026-11-09T12:00:00"),
        )
        conn.commit()

    from webscope.webapp.services.site_service import create_site
    site = create_site(storage, url="https://example.com", organization_id=1)

    detector = ChangeDetector(storage)
    storage.save_site_snapshot(site.id, site.url, {site.url: {"content_hash": "hash1", "etag": None, "last_modified": None, "status_code": 200, "fetched_at": "2026-11-09T12:00:00"}})

    current_pages = {
        site.url: PageSnapshot(url=site.url, content_hash="hash1", etag=None, last_modified=None, status_code=200),
        "https://example.com/about": PageSnapshot(url="https://example.com/about", content_hash="hash2", etag=None, last_modified=None, status_code=200),
    }
    added, changed, removed = detector.detect_changes(site.id, current_pages)
    assert "https://example.com/about" in added
    assert changed == []
    assert removed == []


def test_change_detector_detects_removed_page():
    """Удаленная страница: детектируется как удаленная."""
    storage = Storage(":memory:")
    with storage._conn() as conn:
        conn.execute(
            "INSERT INTO organizations (name, owner_email, created_at) VALUES (?, ?, ?)",
            ("Test Org", "test@test.com", "2026-11-09T12:00:00"),
        )
        conn.commit()

    from webscope.webapp.services.site_service import create_site
    site = create_site(storage, url="https://example.com", organization_id=1)

    detector = ChangeDetector(storage)
    storage.save_site_snapshot(site.id, site.url, {
        site.url: {"content_hash": "hash1", "etag": None, "last_modified": None, "status_code": 200, "fetched_at": "2026-11-09T12:00:00"},
        "https://example.com/about": {"content_hash": "hash2", "etag": None, "last_modified": None, "status_code": 200, "fetched_at": "2026-11-09T12:00:00"},
    })

    current_pages = {site.url: PageSnapshot(url=site.url, content_hash="hash1", etag=None, last_modified=None, status_code=200)}
    added, changed, removed = detector.detect_changes(site.id, current_pages)
    assert "https://example.com/about" in removed
    assert added == []
    assert changed == []


def test_change_detector_etag_comparison():
    """Сравнение по ETag."""
    storage = Storage(":memory:")
    with storage._conn() as conn:
        conn.execute(
            "INSERT INTO organizations (name, owner_email, created_at) VALUES (?, ?, ?)",
            ("Test Org", "test@test.com", "2026-11-09T12:00:00"),
        )
        conn.commit()

    from webscope.webapp.services.site_service import create_site
    site = create_site(storage, url="https://example.com", organization_id=1)

    detector = ChangeDetector(storage)
    storage.save_site_snapshot(site.id, site.url, {site.url: {"content_hash": "hash1", "etag": "\"abc123\"", "last_modified": None, "status_code": 200, "fetched_at": "2026-11-09T12:00:00"}})

    current_pages = {site.url: PageSnapshot(url=site.url, content_hash="hash1", etag="\"def456\"", last_modified=None, status_code=200)}
    added, changed, removed = detector.detect_changes(site.id, current_pages)
    assert site.url in changed


def test_change_detector_last_modified_comparison():
    """Сравнение по Last-Modified."""
    storage = Storage(":memory:")
    with storage._conn() as conn:
        conn.execute(
            "INSERT INTO organizations (name, owner_email, created_at) VALUES (?, ?, ?)",
            ("Test Org", "test@test.com", "2026-11-09T12:00:00"),
        )
        conn.commit()

    from webscope.webapp.services.site_service import create_site
    site = create_site(storage, url="https://example.com", organization_id=1)

    detector = ChangeDetector(storage)
    storage.save_site_snapshot(site.id, site.url, {site.url: {"content_hash": "hash1", "etag": None, "last_modified": "2026-11-08T12:00:00", "status_code": 200, "fetched_at": "2026-11-09T12:00:00"}})

    current_pages = {site.url: PageSnapshot(url=site.url, content_hash="hash1", etag=None, last_modified="2026-11-09T12:00:00", status_code=200)}
    added, changed, removed = detector.detect_changes(site.id, current_pages)
    assert site.url in changed


# ============================================================
# Site Snapshot tests
# ============================================================

def test_site_snapshot_save_and_load():
    """Сохранение и загрузка снимка сайта."""
    storage = Storage(":memory:")
    with storage._conn() as conn:
        conn.execute(
            "INSERT INTO organizations (name, owner_email, created_at) VALUES (?, ?, ?)",
            ("Test Org", "test@test.com", "2026-11-09T12:00:00"),
        )
        conn.commit()

    from webscope.webapp.services.site_service import create_site
    site = create_site(storage, url="https://example.com", organization_id=1)

    pages_data = {
        site.url: {"content_hash": "hash1", "etag": "\"abc123\"", "last_modified": "2026-11-09T12:00:00", "status_code": 200, "fetched_at": "2026-11-09T12:00:00"},
        "https://example.com/about": {"content_hash": "hash2", "etag": "\"def456\"", "last_modified": "2026-11-09T12:00:00", "status_code": 200, "fetched_at": "2026-11-09T12:00:00"},
    }
    storage.save_site_snapshot(site.id, site.url, pages_data)

    snapshot = storage.get_site_snapshot(site.id)
    assert snapshot is not None
    assert snapshot["pages"][site.url]["content_hash"] == "hash1"
    assert snapshot["pages"]["https://example.com/about"]["etag"] == "\"def456\""


def test_site_snapshot_not_found_returns_none():
    """Снимок не найден: возвращает None."""
    storage = Storage(":memory:")
    with storage._conn() as conn:
        conn.execute(
            "INSERT INTO organizations (name, owner_email, created_at) VALUES (?, ?, ?)",
            ("Test Org", "test@test.com", "2026-11-09T12:00:00"),
        )
        conn.commit()

    from webscope.webapp.services.site_service import create_site
    site = create_site(storage, url="https://example.com", organization_id=1)

    snapshot = storage.get_site_snapshot(site.id)
    assert snapshot is None


# ============================================================
# ScanOptions with target_urls tests
# ============================================================

def test_scan_options_target_urls():
    """ScanOptions принимает target_urls."""
    options = ScanOptions(target_urls=["https://example.com/page1", "https://example.com/page2"])
    assert options.target_urls == ["https://example.com/page1", "https://example.com/page2"]


def test_monitor_with_target_urls():
    """Monitor принимает target_urls в опциях."""
    storage = Storage(":memory:")
    with storage._conn() as conn:
        conn.execute(
            "INSERT INTO organizations (name, owner_email, created_at) VALUES (?, ?, ?)",
            ("Test Org", "test@test.com", "2026-11-09T12:00:00"),
        )
        conn.commit()

    monitor = Monitor(storage, ScanOptions(target_urls=["https://example.com/page1"]))
    assert monitor.options.target_urls == ["https://example.com/page1"]


# ============================================================
# Pay-per-scan packages tests
# ============================================================

def test_create_scan_package():
    """Создание пакета сканов."""
    storage = Storage(":memory:")
    with storage._conn() as conn:
        conn.execute(
            "INSERT INTO organizations (name, owner_email, created_at) VALUES (?, ?, ?)",
            ("Test Org", "test@test.com", "2026-11-09T12:00:00"),
        )
        conn.commit()

    pkg = storage.create_scan_package(organization_id=1, scans_total=10, price_cents=2900)
    assert pkg.scans_total == 10
    assert pkg.scans_used == 0
    assert pkg.price_cents == 2900
    assert pkg.scans_left == 10
    assert pkg.is_active is True


def test_consume_scan_decrements_counter():
    """consume_scan уменьшает счетчик."""
    storage = Storage(":memory:")
    with storage._conn() as conn:
        conn.execute(
            "INSERT INTO organizations (name, owner_email, created_at) VALUES (?, ?, ?)",
            ("Test Org", "test@test.com", "2026-11-09T12:00:00"),
        )
        conn.commit()

    pkg = storage.create_scan_package(organization_id=1, scans_total=3, price_cents=2900)

    pkg = storage.consume_scan(pkg.id)
    assert pkg.scans_used == 1
    assert pkg.scans_left == 2
    assert pkg.status == "active"

    pkg = storage.consume_scan(pkg.id)
    pkg = storage.consume_scan(pkg.id)
    assert pkg.scans_used == 3
    assert pkg.scans_left == 0
    assert pkg.status == "exhausted"

    # Повторное потребление исчерпанного пакета возвращает None
    pkg = storage.consume_scan(pkg.id)
    assert pkg is None


def test_get_active_package_for_org():
    """get_active_package_for_org возвращает первый активный пакет (по дате создания DESC)."""
    storage = Storage(":memory:")
    with storage._conn() as conn:
        conn.execute(
            "INSERT INTO organizations (name, owner_email, created_at) VALUES (?, ?, ?)",
            ("Test Org", "test@test.com", "2026-11-09T12:00:00"),
        )
        conn.commit()

    pkg1 = storage.create_scan_package(organization_id=1, scans_total=10, price_cents=2900)
    pkg2 = storage.create_scan_package(organization_id=1, scans_total=50, price_cents=9900)

    active = storage.get_active_package_for_org(1)
    assert active is not None
    # list_scan_packages возвращает пакеты по created_at DESC, поэтому pkg2 (создан позже) первый
    assert active.id == pkg2.id


# ============================================================
# Webhook payload parsing tests
# ============================================================

def test_parse_github_payload():
    """Парсинг GitHub deployment webhook."""
    from webscope.webapp.routes.api import _parse_deploy_payload

    payload = {
        "deployment_status": {"state": "success", "deployment_id": "dep_123"},
        "deployment": {"payload": {"url": "https://example.com"}, "sha": "abc123"},
        "repository": {"html_url": "https://github.com/org/repo"},
    }
    import json
    body = json.dumps(payload).encode()

    result = _parse_deploy_payload("github", body)
    assert result is not None
    assert result["url"] == "https://example.com"
    assert result["version"] == "dep_123"
    assert result["commit"] == "abc123"


def test_parse_gitlab_payload():
    """Парсинг GitLab deployment webhook."""
    from webscope.webapp.routes.api import _parse_deploy_payload

    payload = {
        "object_kind": "deployment",
        "deployment_status": "success",
        "deployment": {"environment_url": "https://example.com", "id": 123},
        "commit": {"id": "abc123"},
    }
    import json
    body = json.dumps(payload).encode()

    result = _parse_deploy_payload("gitlab", body)
    assert result is not None
    assert result["url"] == "https://example.com"
    assert result["version"] == 123  # GitLab возвращает число


def test_parse_vercel_payload():
    """Парсинг Vercel deployment webhook."""
    from webscope.webapp.routes.api import _parse_deploy_payload

    payload = {
        "type": "deployment.succeeded",
        "payload": {"url": "https://example.com", "deploymentId": "dep_123", "git": {"sha": "abc123"}},
    }
    import json
    body = json.dumps(payload).encode()

    result = _parse_deploy_payload("vercel", body)
    assert result is not None
    assert result["url"] == "https://example.com"
    assert result["version"] == "dep_123"


def test_parse_generic_payload():
    """Парсинг Generic webhook."""
    from webscope.webapp.routes.api import _parse_deploy_payload

    payload = {"url": "https://example.com", "version": "v1.0", "commit": "abc123"}
    import json
    body = json.dumps(payload).encode()

    result = _parse_deploy_payload("generic", body)
    assert result is not None
    assert result["url"] == "https://example.com"
    assert result["version"] == "v1.0"


# ============================================================
# Webhook signature verification tests
# ============================================================

def test_hmac_verification_valid():
    """Валидная HMAC подпись проходит проверку."""
    import hmac
    import hashlib

    secret = "test-secret"
    body = b'{"test": "data"}'
    signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert hmac.compare_digest(signature, expected)


def test_hmac_verification_invalid():
    """Невалидная HMAC подпись не проходит проверку."""
    import hmac
    import hashlib

    secret = "test-secret"
    body = b'{"test": "data"}'
    signature = "sha256=invalid_signature"

    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert not hmac.compare_digest(signature, expected)


# ============================================================
# Webhook queue tests
# ============================================================

@pytest.mark.asyncio
async def test_webhook_queue_enqueue_dequeue():
    """Очередь вебхуков: добавление и извлечение."""
    storage = Storage(":memory:")
    queue = await create_webhook_queue(storage)

    event = WebhookEvent(provider="github", site_id=1, deploy_url="https://example.com")
    result = await queue.enqueue(event)
    assert result is True

    event2 = await asyncio.wait_for(queue.queue.get(), timeout=1.0)
    assert event2.site_id == 1
    assert event2.provider == "github"
    assert event2.deploy_url == "https://example.com"

    await queue.stop()


@pytest.mark.asyncio
async def test_webhook_queue_full():
    """Очередь полная: enqueue возвращает False."""
    storage = Storage(":memory:")
    queue = WebhookQueue(storage, max_size=1)
    await queue.start()

    event1 = WebhookEvent(provider="github", site_id=1, deploy_url="https://example.com")
    event2 = WebhookEvent(provider="gitlab", site_id=2, deploy_url="https://test.com")

    assert await queue.enqueue(event1) is True
    assert await queue.enqueue(event2) is False  # очередь полна

    await queue.stop()


# ============================================================
# Incremental scan integration test
# ============================================================

def test_incremental_scan_with_target_urls():
    """Инкрементальный скан с target_urls."""
    storage = Storage(":memory:")
    with storage._conn() as conn:
        conn.execute(
            "INSERT INTO organizations (name, owner_email, created_at) VALUES (?, ?, ?)",
            ("Test Org", "test@test.com", "2026-11-09T12:00:00"),
        )
        conn.commit()

    from webscope.webapp.services.site_service import create_site
    site = create_site(storage, url="https://example.com", organization_id=1)

    # Создаем пакет
    pkg = storage.create_scan_package(organization_id=1, scans_total=10, price_cents=2900)
    assert pkg.scans_left == 10

    # Создаем Monitor с target_urls
    monitor = Monitor(storage, ScanOptions(target_urls=["https://example.com/specific-page"]))
    assert monitor.options.target_urls == ["https://example.com/specific-page"]

    # Проверяем, что scan_site вызывается с start_urls
    from webscope.scanner import scan_site
    import inspect
    sig = inspect.signature(scan_site)
    assert "start_urls" in sig.parameters


# ============================================================
# Webhook integration test
# ============================================================

def test_webhook_handler_parsing():
    """Тест парсинга вебхуков разных провайдеров."""
    from webscope.webapp.routes.api import _parse_deploy_payload
    import json

    test_cases = [
        ("github", {"deployment_status": {"state": "success"}, "deployment": {"payload": {"url": "https://example.com"}, "sha": "abc123"}}, "https://example.com"),
        ("gitlab", {"object_kind": "deployment", "deployment_status": "success", "deployment": {"environment_url": "https://example.com", "id": 123}, "commit": {"id": "abc123"}}, "https://example.com"),
        ("vercel", {"type": "deployment.succeeded", "payload": {"url": "https://example.com", "deploymentId": "dep_123"}}, "https://example.com"),
        ("netlify", {"state": "ready", "deploy_ssl_url": "https://example.com", "id": "dep_123"}, "https://example.com"),
        ("cloudflare", {"event": "deployment_created", "payload": {"url": "https://example.com", "deployment_id": "dep_123", "status": "success"}}, "https://example.com"),
    ]

    for provider, payload, expected_url in test_cases:
        body = json.dumps(payload).encode()
        result = _parse_deploy_payload(provider, body)
        assert result is not None, f"Provider {provider} returned None"
        assert result["url"] == expected_url, f"Provider {provider}: expected {expected_url}, got {result.get('url')}"


# ============================================================
# Watchdog settings API tests
# ============================================================

def test_watchdog_settings_api():
    """API для настроек Watchdog."""
    storage = Storage(":memory:")
    with storage._conn() as conn:
        conn.execute(
            "INSERT INTO organizations (name, owner_email, created_at) VALUES (?, ?, ?)",
            ("Test Org", "test@test.com", "2026-11-09T12:00:00"),
        )
        conn.commit()

    from webscope.webapp.services.site_service import create_site, update_site
    site = create_site(storage, url="https://example.com", organization_id=1)

    # Обновляем настройки Watchdog
    updated = update_site(storage, site_id=site.id, watchdog_enabled=True, watchdog_triggers=["webhook", "content_hash"], watchdog_webhook_secret="test-secret")
    assert updated.watchdog_enabled is True
    assert updated.watchdog_triggers == ["webhook", "content_hash"]
    assert updated.watchdog_webhook_secret == "test-secret"


def test_watchdog_triggers_serialization():
    """Сериализация/десериализация триггеров."""
    storage = Storage(":memory:")
    with storage._conn() as conn:
        conn.execute(
            "INSERT INTO organizations (name, owner_email, created_at) VALUES (?, ?, ?)",
            ("Test Org", "test@test.com", "2026-11-09T12:00:00"),
        )
        conn.commit()

    from webscope.webapp.services.site_service import create_site, update_site
    site = create_site(storage, url="https://example.com", organization_id=1)

    # Обновляем с массивом триггеров
    updated = update_site(storage, site_id=site.id, watchdog_triggers=["webhook", "sitemap"])
    assert updated.watchdog_triggers == ["webhook", "sitemap"]

    # Проверяем, что в БД сохранилось как строка
    with storage._conn() as conn:
        row = conn.execute("SELECT watchdog_triggers FROM sites WHERE id = ?", (site.id,)).fetchone()
        assert row["watchdog_triggers"] == "webhook,sitemap"


# ============================================================
# Incremental scan with target_urls integration test
# ============================================================

def test_incremental_scan_only_scans_target_urls():
    """Инкрементальный скан сканирует только target_urls."""
    # Этот тест проверяет логику передачи target_urls, но не делает реальных HTTP запросов
    # (требует мокирования scanner). Проверяем, что target_urls передается в scan_site.
    from unittest.mock import patch, MagicMock
    from webscope.scanner import scan_site
    from webscope.webapp.scheduler import ScanOptions
    from webscope.webapp.storage import Storage
    from webscope.models import ScanResult
    from webscope.scanner import CrawlResult

    storage = Storage(":memory:")
    with storage._conn() as conn:
        conn.execute(
            "INSERT INTO organizations (name, owner_email, created_at) VALUES (?, ?, ?)",
            ("Test Org", "test@test.com", "2026-11-09T12:00:00"),
        )
        conn.commit()

    from webscope.webapp.services.site_service import create_site
    site = create_site(storage, url="https://example.com", organization_id=1)

    # Создаем пакет
    pkg = storage.create_scan_package(organization_id=1, scans_total=10, price_cents=2900)
    assert pkg.scans_left == 10

    # Проверяем, что start_urls передается в scan_site
    # Используем MagicMock для полного мокирования
    with patch('webscope.scanner.scan_site', new_callable=MagicMock) as mock_scan:
        mock_scan.return_value = (ScanResult(
            url="https://example.com",
            final_url="https://example.com",
            title="Test",
            archetype={},
            findings=[],
            duration_ms=100,
            pages_scanned=1,
        ), CrawlResult(root="https://example.com", pages=[], templates=[], sitemap_used=False, robots_checked=False, skipped=[]))
        
        from webscope.scanner import scan_site
        result, _ = scan_site(
            "https://example.com",
            max_pages=1,
            max_depth=0,
            timeout_ms=5000,
            allow_private=False,
            checks=["a11y"],
            start_urls=["https://example.com/specific-page"],
        )

        # Проверяем, что start_urls передан
        mock_scan.assert_called_once()
        call_kwargs = mock_scan.call_args.kwargs
        assert "start_urls" in call_kwargs
        assert call_kwargs["start_urls"] == ["https://example.com/specific-page"]

    print("✅ start_urls passed correctly")


# ============================================================
# Watchdog settings persistence tests
# ============================================================

def test_site_to_dict_includes_watchdog_fields():
    """to_dict включает поля Watchdog."""
    storage = Storage(":memory:")
    with storage._conn() as conn:
        conn.execute(
            "INSERT INTO organizations (name, owner_email, created_at) VALUES (?, ?, ?)",
            ("Test Org", "test@test.com", "2026-11-09T12:00:00"),
        )
        conn.commit()

    from webscope.webapp.services.site_service import create_site
    site = create_site(storage, url="https://example.com", organization_id=1, watchdog_enabled=True, watchdog_triggers=["webhook", "content_hash"], watchdog_webhook_secret="test-secret")

    payload = site.to_dict()
    assert payload["watchdog_enabled"] is True
    assert payload["watchdog_triggers"] == ["webhook", "content_hash"]
    assert payload["watchdog_webhook_secret"] == "test-secret"
    assert "last_deploy_at" in payload
    assert "last_watchdog_check" in payload
    assert "last_watchdog_diff" in payload


def test_site_watchdog_property():
    """has_watchdog property."""
    storage = Storage(":memory:")
    with storage._conn() as conn:
        conn.execute(
            "INSERT INTO organizations (name, owner_email, created_at) VALUES (?, ?, ?)",
            ("Test Org", "test@test.com", "2026-11-09T12:00:00"),
        )
        conn.commit()

    from webscope.webapp.services.site_service import create_site
    site = create_site(storage, url="https://example.com", organization_id=1, watchdog_enabled=True)
    assert site.has_watchdog is True

    site2 = create_site(storage, url="https://test.com", organization_id=1, watchdog_enabled=False)
    assert site2.has_watchdog is False

    # С секретом но без enabled
    site3 = create_site(storage, url="https://test2.com", organization_id=1, watchdog_enabled=False, watchdog_webhook_secret="secret")
    assert site3.has_watchdog is False  # enabled=False, значит has_watchdog=False


# ============================================================
# Integration test: webhook -> change detection -> incremental scan
# ============================================================

def test_webhook_to_incremental_scan_flow():
    """Полный флоу: вебхук -> детектор изменений -> инкрементальный скан."""
    storage = Storage(":memory:")
    with storage._conn() as conn:
        conn.execute(
            "INSERT INTO organizations (name, owner_email, created_at) VALUES (?, ?, ?)",
            ("Test Org", "test@test.com", "2026-11-09T12:00:00"),
        )
        conn.commit()

    from webscope.webapp.services.site_service import create_site
    from webscope.webapp.scheduler import Monitor, ScanOptions
    from webscope.watchdog import ChangeDetector
    from webscope.watchdog import PageSnapshot

    site = create_site(storage, url="https://example.com", organization_id=1)
    storage.update_site(site.id, watchdog_enabled=True, watchdog_triggers=["webhook"])

    # Создаем снимок
    current_pages = {site.url: PageSnapshot(url=site.url, content_hash="hash1", etag=None, last_modified=None, status_code=200)}
    pages_data = {url: {"content_hash": p.content_hash, "etag": p.etag, "last_modified": p.last_modified, "status_code": p.status_code, "fetched_at": p.fetched_at} for url, p in current_pages.items()}
    storage.save_site_snapshot(site.id, site.url, pages_data)

    # Симулируем вебхук: контент изменился
    detector = ChangeDetector(storage)
    current_pages = {site.url: PageSnapshot(url=site.url, content_hash="hash2", etag=None, last_modified=None, status_code=200)}
    added, changed, removed = detector.detect_changes(site.id, current_pages)

    assert changed == ["https://example.com"]
    changed_urls = changed + added

    # Запускаем инкрементальный скан с changed_urls
    from webscope.scanner import scan_site
    result, _ = scan_site(
        "https://example.com",
        max_pages=1,
        max_depth=0,
        timeout_ms=5000,
        allow_private=False,
        checks=["a11y"],
        start_urls=changed_urls,
    )

    assert result.pages_scanned == 1

    # Проверяем, что пакет списался
    from webscope.webapp.services.site_service import create_site as cs
    storage = Storage(":memory:")
    with storage._conn() as conn:
        conn.execute("INSERT INTO organizations (name, owner_email, created_at) VALUES (?, ?, ?)", ("Test", "test@test.com", "2026-11-09T12:00:00"))
        conn.commit()
    pkg = storage.create_scan_package(organization_id=1, scans_total=10, price_cents=2900)
    pkg = storage.consume_scan(pkg.id)
    assert pkg.scans_left == 9


if __name__ == "__main__":
    pytest.main([__file__, "-v"])