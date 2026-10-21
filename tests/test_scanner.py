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
