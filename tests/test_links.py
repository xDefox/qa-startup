"""Юнит-тесты проверки внутренних ссылок.

Сетевые ошибки различаются по смыслу: таймаут — это «не дождались», а не
«ссылки нет». Такая находка диагностическая и балл сайта не снижает.
"""

from __future__ import annotations

import pytest

from webscope.checks.links import _error_rule
from webscope.models import Finding, Severity
from webscope.scoring import compute_score, is_diagnostic


@pytest.mark.parametrize(
    "error",
    ["TimeoutException", "ConnectTimeout", "ReadTimeout", "WriteTimeout", "PoolTimeout", "TimeoutError"],
)
def test_timeout_errors_are_diagnostic(error: str) -> None:
    rule, severity = _error_rule(error)
    assert rule == "links/timeout"
    assert severity is Severity.MINOR


@pytest.mark.parametrize("error", ["ConnectError", "RemoteProtocolError", "TooManyRedirects", "SSLError"])
def test_other_network_errors_stay_defects(error: str) -> None:
    rule, severity = _error_rule(error)
    assert rule == "links/unreachable"
    assert severity is Severity.MODERATE


def _finding(rule: str, severity: Severity) -> Finding:
    return Finding(rule=rule, severity=severity, title="t", message="", url="https://example.com/")


def test_timeout_finding_does_not_lower_score() -> None:
    finding = _finding("links/timeout", Severity.MINOR)
    assert is_diagnostic(finding) is True
    assert compute_score([finding]) == 100


def test_unreachable_finding_lowers_score() -> None:
    finding = _finding("links/unreachable", Severity.MODERATE)
    assert is_diagnostic(finding) is False
    assert compute_score([finding]) < 100
