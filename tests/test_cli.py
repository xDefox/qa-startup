"""Тесты CLI: baseline со стабильными селекторами и snippet-страховкой."""

from __future__ import annotations

import json
from pathlib import Path

from webscope.cli import _is_known, _load_baseline, _snippet_key
from webscope.models import Finding, Severity


def _finding(rule: str, selector: str | None, snippet: str | None) -> Finding:
    return Finding(
        rule=rule,
        severity=Severity.SERIOUS,
        title="тест",
        message="тест",
        url="https://site.com/",
        selector=selector,
        snippet=snippet,
    )


def test_snippet_key_normalizes_whitespace() -> None:
    assert _snippet_key("<img   src='/a.png' >") == _snippet_key("  <img src='/a.png'> ")
    assert _snippet_key(None) == ""


def test_baseline_matches_by_selector_and_snippet(tmp_path: Path) -> None:
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(
        json.dumps(
            {
                "findings": [
                    {"rule": "content/image-alt", "selector": "#logo", "snippet": "<img src='/logo.png'>"},
                ]
            }
        ),
        encoding="utf-8",
    )

    baseline = _load_baseline(baseline_path)
    # точное совпадение по селектору — известная проблема
    assert _is_known(_finding("content/image-alt", "#logo", "<img src='/logo.png'>"), baseline)
    # селектор сдвинулся — находим ту же проблему по фрагменту
    assert _is_known(_finding("content/image-alt", "header > img", "<img src='/logo.png'>"), baseline)
    # другой элемент или правило — уже не известное
    assert not _is_known(_finding("content/image-alt", "#banner", "<img src='/banner.png'>"), baseline)
    assert not _is_known(_finding("content/missing-title", "#logo", "<img src='/logo.png'>"), baseline)


def test_baseline_empty_when_no_path() -> None:
    baseline = _load_baseline(None)
    assert not _is_known(_finding("content/image-alt", "#logo", "<img>"), baseline)
