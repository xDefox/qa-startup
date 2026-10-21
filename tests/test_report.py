"""Тесты отчётов и fix-prompt."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET

from webscope.models import Finding, ScanResult, Severity
from webscope.report import build_fix_prompt, render_html, render_json, render_junit, render_sarif, render_text


def _result() -> ScanResult:
    return ScanResult(
        url="https://example.com",
        final_url="https://example.com/",
        title="Example",
        archetype={"framework": "next", "cms": None, "ui_kit": "tailwind"},
        findings=[
            Finding(
                rule="content/image-alt",
                severity=Severity.SERIOUS,
                title="Изображение без alt",
                message="У <img> нет атрибута alt",
                url="https://example.com/",
                selector="main > img",
                snippet='<img src="/logo.png">',
                help_url="https://www.w3.org/WAI/WCAG22/Understanding/non-text-content.html",
            )
        ],
    )


def test_render_text_contains_rule() -> None:
    text = render_text(_result())
    assert "content/image-alt" in text
    assert "SERIOUS" in text


def test_render_json_roundtrip() -> None:
    data = json.loads(render_json(_result()))
    assert data["schema_version"] == "1.0"
    assert data["summary"]["serious"] == 1
    assert data["findings"][0]["selector"] == "main > img"


def test_render_sarif_is_valid_json() -> None:
    data = json.loads(render_sarif(_result()))
    assert data["version"] == "2.1.0"
    run = data["runs"][0]
    assert run["tool"]["driver"]["name"] == "webscope"
    assert run["results"][0]["ruleId"] == "content/image-alt"
    assert run["results"][0]["level"] == "error"


def test_render_junit_is_valid_xml() -> None:
    xml = render_junit(_result())
    root = ET.fromstring(xml)
    assert root.tag == "testsuite"
    assert root.attrib["tests"] == "1"


def test_render_html_contains_escape() -> None:
    html = render_html(_result())
    assert "<html" in html
    assert "content/image-alt" in html


def test_fix_prompt_contains_acceptance_criteria() -> None:
    prompt = build_fix_prompt(_result())
    assert "content/image-alt" in prompt
    assert "приёмка:" in prompt
    assert "alt" in prompt
    assert "webscope scan" in prompt


def test_fix_prompt_without_findings() -> None:
    empty = ScanResult(url="https://example.com", final_url="https://example.com/")
    prompt = build_fix_prompt(empty)
    assert "находок webscope нет" in prompt
