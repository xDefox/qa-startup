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
