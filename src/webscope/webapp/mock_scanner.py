"""Детерминированный сканер для тестов и демо-режима."""

from __future__ import annotations

from ..models import Finding, ScanResult, Severity
from .scheduler import CrawlOutcome, ScanOptions


def mock_scanner(url: str, options: ScanOptions) -> CrawlOutcome:
    """Мгновенный результат: две находки, без браузера и сети."""
    findings = [
        Finding(
            rule="content/image-alt",
            severity=Severity.SERIOUS,
            title="Изображение без alt",
            message="У <img> нет атрибута alt",
            url=url,
            selector="main > img",
            snippet="<img src='/logo.png'>",
            help_url="https://www.w3.org/WAI/WCAG22/Understanding/non-text-content.html",
            source="webscope.content",
            details={"evidence": "001_content_image_alt.png"},
        ),
        Finding(
            rule="forms/control-without-label",
            severity=Severity.MODERATE,
            title="Поле без подписи",
            message="У поля нет <label>",
            url=url,
            selector="input[name='email']",
            snippet="<input name='email'>",
            help_url="https://www.w3.org/WAI/WCAG22/Understanding/label-in-name.html",
            source="webscope.forms",
            details={},
        ),
    ]
    result = ScanResult(
        url=url,
        final_url=url,
        title="Test Site",
        findings=findings,
        duration_ms=5000,
        pages_scanned=3,
    )
    return CrawlOutcome(result)


__all__ = ["mock_scanner"]
