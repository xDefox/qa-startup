"""Тесты оценки и человеческого языка."""

from __future__ import annotations

from webscope.models import Finding, Severity
from webscope.scoring import compute_score, plain_impact, score_label, top_actions


def _finding(rule: str, severity: Severity, url: str = "https://site.com/") -> Finding:
    return Finding(rule=rule, severity=severity, title=rule, message="", url=url)


def test_score_is_100_without_findings() -> None:
    assert compute_score([]) == 100


def test_score_drops_with_findings() -> None:
    score = compute_score([_finding("content/image-alt", Severity.SERIOUS)])
    assert score < 100
    assert score >= 70


def test_score_is_capped_per_rule() -> None:
    many = [_finding("content/image-alt", Severity.SERIOUS, f"https://site.com/{i}") for i in range(30)]
    few = [_finding("content/image-alt", Severity.SERIOUS)]
    assert compute_score(many) == compute_score(few)


def test_score_never_negative() -> None:
    findings = [_finding(f"rule-{i}", Severity.CRITICAL) for i in range(50)]
    assert compute_score(findings) == 0


def test_plain_impact_known_rule() -> None:
    meaning, fix = plain_impact(_finding("content/image-alt", Severity.SERIOUS))
    assert "alt" in fix.lower()
    assert meaning


def test_plain_impact_unknown_rule_has_fallback() -> None:
    meaning, fix = plain_impact(_finding("some-unknown-rule", Severity.MINOR))
    assert meaning and fix


def test_top_actions_prefers_severity() -> None:
    findings = [
        _finding("content/image-alt", Severity.MINOR),
        _finding("links/broken", Severity.CRITICAL),
        _finding("content/missing-title", Severity.MODERATE),
    ]
    actions = top_actions(findings, limit=2)
    assert [finding.rule for finding in actions] == ["links/broken", "content/missing-title"]


def test_score_label() -> None:
    assert score_label(95) == "отлично"
    assert score_label(10) == "критично плохо"
