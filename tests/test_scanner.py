"""Тесты безопасности цели сканирования (SSRF-защита)."""

from __future__ import annotations

import pytest

from webscope.scanner import ScanError, validate_target


def test_rejects_non_http_scheme() -> None:
    with pytest.raises(ScanError):
        validate_target("file:///etc/passwd")


def test_rejects_credentials_in_url() -> None:
    with pytest.raises(ScanError):
        validate_target("https://user:pass@example.com")


def test_rejects_localhost() -> None:
    with pytest.raises(ScanError):
        validate_target("http://127.0.0.1:8000/admin")


def test_rejects_private_network() -> None:
    with pytest.raises(ScanError):
        validate_target("http://192.168.1.1/")


def test_allows_public_url() -> None:
    assert validate_target("https://example.com") == "https://example.com"


def test_allows_private_when_explicitly_allowed() -> None:
    assert validate_target("http://127.0.0.1:8000", allow_private=True) == "http://127.0.0.1:8000"


def test_dedupe_drops_axe_duplicates() -> None:
    from webscope.models import Finding, Severity
    from webscope.scanner import _dedupe_findings

    own = Finding(
        rule="content/image-alt",
        severity=Severity.SERIOUS,
        title="Изображение без alt",
        message="",
        url="https://example.com/",
        selector="html > body > img",
        snippet='<img src="/logo.png">',
        source="webscope.content",
    )
    axe = Finding(
        rule="image-alt",
        severity=Severity.CRITICAL,
        title="Images must have alternative text",
        message="",
        url="https://example.com/",
        selector="img",
        snippet='<img src="/logo.png">',
        source="webscope.a11y",
    )
    other = Finding(
        rule="content/missing-title",
        severity=Severity.SERIOUS,
        title="Пустой title",
        message="",
        url="https://example.com/",
        source="webscope.content",
    )

    deduped = _dedupe_findings([own, axe, other])
    rules = [finding.rule for finding in deduped]
    assert rules == ["content/image-alt", "content/missing-title"]


def test_dedupe_drops_axe_document_duplicates_by_url() -> None:
    """Проверки уровня документа без сниппета сопоставляются по URL страницы.

    Регресс-тест: html-has-lang (сниппет <html>) и наш content/missing-lang
    (сниппета нет) на varkacoffee.by давали 20+20 — один дефект дважды.
    """
    from webscope.models import Finding, Severity
    from webscope.scanner import _dedupe_findings

    own = Finding(
        rule="content/missing-lang",
        severity=Severity.SERIOUS,
        title="Нет атрибута lang",
        message="",
        url="https://example.com/menu",
        source="webscope.content",
    )
    axe = Finding(
        rule="html-has-lang",
        severity=Severity.CRITICAL,
        title="html element must have a lang",
        message="",
        url="https://example.com/menu",
        selector="html",
        snippet="<html>",
        source="webscope.a11y",
    )
    other_page = Finding(
        rule="html-has-lang",
        severity=Severity.CRITICAL,
        title="html element must have a lang",
        message="",
        url="https://example.com/about",
        selector="html",
        snippet="<html>",
        source="webscope.a11y",
    )

    deduped = _dedupe_findings([own, axe, other_page])
    rules = [(f.rule, f.url) for f in deduped]
    # Дубль на той же странице убран, другая страница axe — осталась.
    assert rules == [
        ("content/missing-lang", "https://example.com/menu"),
        ("html-has-lang", "https://example.com/about"),
    ]


def test_dedupe_keeps_axe_rule_without_own_equivalent() -> None:
    from webscope.models import Finding, Severity
    from webscope.scanner import _dedupe_findings

    axe = Finding(
        rule="color-contrast",
        severity=Severity.SERIOUS,
        title="Контраст",
        message="",
        url="https://example.com/",
        snippet="<p>text</p>",
        source="webscope.a11y",
    )
    assert _dedupe_findings([axe]) == [axe]


def test_validate_target_dns_failure_is_human_readable() -> None:
    # хост, который не резолвится, — сообщение должно быть про домен, а не про сокет
    with pytest.raises(ScanError) as excinfo:
        validate_target("https://this-host-does-not-exist-xyzqwe.invalid/")
    assert "домен не найден" in str(excinfo.value)
    assert "this-host-does-not-exist-xyzqwe.invalid" in str(excinfo.value)


def test_diagnose_navigation_error_dns() -> None:
    from playwright.sync_api import Error as PlaywrightError

    from webscope.diagnostics import diagnose_navigation_error

    exc = PlaywrightError("page.goto: net::ERR_NAME_NOT_RESOLVED at https://x.com/")
    message = diagnose_navigation_error("https://x.com/", exc)
    assert "домен не найден" in message


def test_diagnose_navigation_error_timeout() -> None:
    from playwright.sync_api import Error as PlaywrightError

    from webscope.diagnostics import diagnose_navigation_error

    exc = PlaywrightError("Timeout 30000ms exceeded.")
    message = diagnose_navigation_error("https://slow.com/", exc, timeout_ms=30000)
    assert "не загрузилась за 30 с" in message


def test_diagnose_navigation_error_certificate() -> None:
    from playwright.sync_api import Error as PlaywrightError

    from webscope.diagnostics import diagnose_navigation_error

    exc = PlaywrightError("page.goto: net::ERR_CERT_AUTHORITY_INVALID at https://x.com/")
    message = diagnose_navigation_error("https://x.com/", exc)
    assert "сертификат" in message.lower()


def test_diagnose_navigation_error_connection_refused() -> None:
    from playwright.sync_api import Error as PlaywrightError

    from webscope.diagnostics import diagnose_navigation_error

    exc = PlaywrightError("page.goto: net::ERR_CONNECTION_REFUSED at http://127.0.0.1:9/")
    message = diagnose_navigation_error("http://127.0.0.1:9/", exc)
    assert "соединение" in message.lower()


def test_diagnose_http_error_known_statuses() -> None:
    from webscope.diagnostics import diagnose_http_error

    assert "не найдена" in diagnose_http_error("https://x.com/missing", 404)
    assert "HTTP 404" in diagnose_http_error("https://x.com/missing", 404)
    assert "ошибка на сервере" in diagnose_http_error("https://x.com/", 500)


def test_diagnose_http_error_unknown_status() -> None:
    from webscope.diagnostics import diagnose_http_error

    message = diagnose_http_error("https://x.com/", 418)
    assert "HTTP 418" in message


def test_dedupe_drops_axe_frame_title_duplicate() -> None:
    """Регресс: axe frame-title и наш content/frame-title — один iframe.

    В _AXE_EQUIVALENTS стояла опечатка content/iframe-title, поэтому дедуп не
    срабатывал и iframe без title попадал в отчёт дважды (varkacoffee.by).
    """
    from webscope.models import Finding, Severity
    from webscope.scanner import _dedupe_findings

    own = Finding(
        rule="content/frame-title",
        severity=Severity.MODERATE,
        title="iframe без заголовка",
        message="",
        url="https://example.com/",
        selector="iframe",
        snippet='<iframe src="https://yandex.ru/map-widget/v1/"></iframe>',
        source="webscope.content",
    )
    axe = Finding(
        rule="frame-title",
        severity=Severity.SERIOUS,
        title="Frames must have an accessible name",
        message="",
        url="https://example.com/",
        selector="iframe",
        snippet='<iframe src="https://yandex.ru/map-widget/v1/"></iframe>',
        source="webscope.a11y",
    )

    assert [f.rule for f in _dedupe_findings([own, axe])] == ["content/frame-title"]
