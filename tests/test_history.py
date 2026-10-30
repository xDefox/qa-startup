"""Тесты снимков, диффов и истории."""

from __future__ import annotations

from pathlib import Path

from webscope.history import diff_snapshots, list_snapshots, load_snapshot, save_snapshot, snapshot_from_result, trend
from webscope.models import Finding, ScanResult, Severity


def _finding(rule: str, severity: Severity, url: str = "https://site.com/", selector: str = "main > img") -> Finding:
    return Finding(
        rule=rule,
        severity=severity,
        title=rule,
        message="",
        url=url,
        selector=selector,
        snippet="<img src='/a.png'>",
    )


def _snapshot(findings: list[Finding], taken_at: str = "2026-10-21T10:00:00+00:00"):
    result = ScanResult(url="https://site.com/", final_url="https://site.com/", findings=findings)
    snapshot = snapshot_from_result(result)
    snapshot.taken_at = taken_at
    return snapshot


def test_snapshot_keeps_findings_and_score(tmp_path: Path) -> None:
    snapshot = _snapshot([_finding("content/image-alt", Severity.SERIOUS)])
    path = save_snapshot(snapshot, tmp_path)
    loaded = load_snapshot(path)
    assert loaded.url == "https://site.com/"
    assert loaded.score == snapshot.score
    assert len(loaded.findings) == 1


def test_diff_detects_new_and_fixed() -> None:
    old = _snapshot([_finding("content/image-alt", Severity.SERIOUS)])
    new = _snapshot(
        [
            _finding("content/image-alt", Severity.SERIOUS),
            _finding("content/missing-title", Severity.MODERATE),
        ]
    )
    diff = diff_snapshots(old, new)
    assert [entry.rule for entry in diff.new_findings] == ["content/missing-title"]
    assert diff.fixed_findings == []
    assert diff.score_after < diff.score_before


def test_diff_detects_fixed() -> None:
    old = _snapshot([_finding("content/image-alt", Severity.SERIOUS)])
    new = _snapshot([])
    diff = diff_snapshots(old, new)
    assert [entry.rule for entry in diff.fixed_findings] == ["content/image-alt"]
    assert diff.score_after > diff.score_before
    assert diff.is_improvement


def test_diff_detects_severity_change() -> None:
    old = _snapshot([_finding("content/image-alt", Severity.MODERATE)])
    new = _snapshot([_finding("content/image-alt", Severity.CRITICAL)])
    diff = diff_snapshots(old, new)
    assert len(diff.changed_findings) == 1
    assert diff.changed_findings[0].severity_before == "moderate"
    assert diff.changed_findings[0].severity_after == "critical"


def test_diff_selector_shift_is_not_new_and_fixed() -> None:
    """Сдвиг селектора (например, из-за нового блока выше) — не новая и не «исправленная» проблема."""
    old = _snapshot([_finding("content/image-alt", Severity.SERIOUS, selector="main > img")])
    new = _snapshot([_finding("content/image-alt", Severity.SERIOUS, selector="main > div > img")])
    diff = diff_snapshots(old, new)
    assert diff.new_findings == []
    assert diff.fixed_findings == []
    assert diff.changed_findings == []


def test_diff_severity_change_via_element_match() -> None:
    """Смена серьёзности распознаётся даже при сдвинутом селекторе."""
    old = _snapshot([_finding("content/image-alt", Severity.MODERATE, selector="main > img")])
    new = _snapshot([_finding("content/image-alt", Severity.CRITICAL, selector="main > div > img")])
    diff = diff_snapshots(old, new)
    assert diff.new_findings == []
    assert diff.fixed_findings == []
    assert len(diff.changed_findings) == 1
    assert diff.changed_findings[0].severity_before == "moderate"
    assert diff.changed_findings[0].severity_after == "critical"


def test_worsened_findings_flags_only_upgrades() -> None:
    """«Ухудшение» — только рост серьёзности; улучшение к нему не относится."""
    worse = diff_snapshots(
        _snapshot([_finding("content/image-alt", Severity.MODERATE)]),
        _snapshot([_finding("content/image-alt", Severity.CRITICAL)]),
    )
    assert [entry.rule for entry in worse.worsened_findings] == ["content/image-alt"]

    better = diff_snapshots(
        _snapshot([_finding("content/image-alt", Severity.CRITICAL)]),
        _snapshot([_finding("content/image-alt", Severity.MODERATE)]),
    )
    assert better.worsened_findings == []


def test_slug_unique_for_long_similar_urls() -> None:
    """URL с одинаковым длинным началом не должны попадать в один каталог истории."""
    from webscope.history import _slug

    prefix = "https://site.com/search?" + "&".join(f"q={index}" for index in range(30))
    assert _slug(prefix + "&page=1") != _slug(prefix + "&page=2")


def test_history_trend_and_listing(tmp_path: Path) -> None:
    save_snapshot(_snapshot([], "2026-10-20T10:00:00+00:00"), tmp_path)
    save_snapshot(_snapshot([_finding("content/image-alt", Severity.SERIOUS)], "2026-10-21T10:00:00+00:00"), tmp_path)

    paths = list_snapshots(tmp_path, "https://site.com/")
    assert len(paths) == 2

    points = trend(tmp_path, "https://site.com/")
    assert len(points) == 2
    assert points[-1]["serious"] == 1
    assert points[0]["score"] == 100


def _bare(rule: str, severity: Severity, title: str = "t") -> Finding:
    """Находка без селектора и сниппета — как у документных правил."""
    return Finding(rule=rule, severity=severity, title=title, message="", url="https://site.com/")


def test_diff_keeps_new_duplicates_without_selector() -> None:
    """Несколько находок одного правила без селектора не должны схлопываться.

    Регресс: dict по ключу (rule, url, selector) терял все повторы, и дифф
    показывал «новых проблем: 0», хотя на странице появились два дубля id.
    """
    old = _snapshot([_bare("content/duplicate-id", Severity.MODERATE, "dup a")])
    new = _snapshot(
        [
            _bare("content/duplicate-id", Severity.MODERATE, "dup a"),
            _bare("content/duplicate-id", Severity.MODERATE, "dup b"),
            _bare("content/duplicate-id", Severity.MODERATE, "dup c"),
        ]
    )
    diff = diff_snapshots(old, new)
    assert len(diff.new_findings) == 2
    assert diff.fixed_findings == []


def test_diff_keeps_fixed_duplicates_without_selector() -> None:
    old = _snapshot([_bare("content/duplicate-id", Severity.MODERATE, f"dup {index}") for index in range(3)])
    new = _snapshot([_bare("content/duplicate-id", Severity.MODERATE, "dup 0")])
    diff = diff_snapshots(old, new)
    assert len(diff.fixed_findings) == 2
    assert diff.new_findings == []
