"""Юнит-тесты моделей: severity, сводка, сортировка."""

from __future__ import annotations

from webscope.models import Finding, ScanResult, Severity, severity_from_impact, sort_findings


def _finding(rule: str, severity: Severity) -> Finding:
    return Finding(rule=rule, severity=severity, title=rule, message="", url="https://example.com")


def test_severity_rank_order() -> None:
    assert Severity.CRITICAL.rank < Severity.SERIOUS.rank < Severity.MODERATE.rank < Severity.MINOR.rank


def test_severity_from_impact() -> None:
    assert severity_from_impact("critical") is Severity.CRITICAL
    assert severity_from_impact("serious") is Severity.SERIOUS
    assert severity_from_impact("minor") is Severity.MINOR
    assert severity_from_impact(None) is Severity.MODERATE
    assert severity_from_impact("что-то") is Severity.MODERATE


def test_summary_counts_findings() -> None:
    result = ScanResult(
        url="https://example.com",
        findings=[
            _finding("a", Severity.CRITICAL),
            _finding("b", Severity.MINOR),
            _finding("c", Severity.MINOR),
        ],
    )
    summary = result.summary
    assert summary == {"critical": 1, "serious": 0, "moderate": 0, "minor": 2, "total": 3}


def test_sort_findings_by_severity_then_rule() -> None:
    findings = [
        _finding("z-rule", Severity.MINOR),
        _finding("a-rule", Severity.SERIOUS),
        _finding("m-rule", Severity.MINOR),
    ]
    ordered = sort_findings(findings)
    assert [f.rule for f in ordered] == ["a-rule", "m-rule", "z-rule"]


def test_to_dict_is_json_serialisable() -> None:
    import json

    result = ScanResult(url="https://example.com", findings=[_finding("a", Severity.SERIOUS)])
    payload = json.dumps(result.to_dict(), ensure_ascii=False)
    assert '"schema_version": "1.0"' in payload
    assert '"severity": "serious"' in payload
