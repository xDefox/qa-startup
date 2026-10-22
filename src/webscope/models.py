"""Схема данных webscope.

Формат JSON версионируется через ``schema_version`` (semver).
Обратная совместимость: поля только добавляются, существующие не меняются.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

SCHEMA_VERSION = "1.0"


class Severity(str, Enum):
    """Уровень серьёзности находки."""

    CRITICAL = "critical"
    SERIOUS = "serious"
    MODERATE = "moderate"
    MINOR = "minor"

    @property
    def rank(self) -> int:
        """Чем меньше значение, тем серьёзнее находка."""
        return _SEVERITY_RANK[self]

    def __str__(self) -> str:  # pragma: no cover - тривиально
        return self.value


_SEVERITY_RANK = {
    Severity.CRITICAL: 0,
    Severity.SERIOUS: 1,
    Severity.MODERATE: 2,
    Severity.MINOR: 3,
}

_IMPACT_TO_SEVERITY = {
    "critical": Severity.CRITICAL,
    "serious": Severity.SERIOUS,
    "moderate": Severity.MODERATE,
    "minor": Severity.MINOR,
}


def severity_from_impact(impact: str | None) -> Severity:
    """Маппит impact из axe-core в нашу шкалу severity."""
    return _IMPACT_TO_SEVERITY.get((impact or "").strip().lower(), Severity.MODERATE)


@dataclass
class Finding:
    """Одна подтверждённая находка.

    Находка всегда привязана к конкретному элементу страницы: селектор + сниппет +
    (опционально) скриншот. Находка без локации — это не находка, а мнение.
    """

    rule: str
    severity: Severity
    title: str
    message: str
    url: str
    selector: str | None = None
    snippet: str | None = None
    help_url: str | None = None
    source: str = "webscope"
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["severity"] = self.severity.value
        return data


@dataclass
class ScanResult:
    """Результат сканирования одной цели."""

    url: str
    findings: list[Finding] = field(default_factory=list)
    final_url: str | None = None
    title: str | None = None
    archetype: dict[str, Any] = field(default_factory=dict)
    duration_ms: int = 0
    pages_scanned: int = 0
    schema_version: str = SCHEMA_VERSION
    generated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))

    @property
    def summary(self) -> dict[str, int]:
        counts = {severity.value: 0 for severity in Severity}
        for finding in self.findings:
            counts[finding.severity.value] += 1
        counts["total"] = len(self.findings)
        return counts

    @property
    def score(self) -> int:
        """Оценка «здоровья» 0–100 (логика — в scoring.compute_score)."""
        from .scoring import compute_score

        return compute_score(self.findings)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at,
            "url": self.url,
            "final_url": self.final_url,
            "title": self.title,
            "archetype": self.archetype,
            "duration_ms": self.duration_ms,
            "pages_scanned": self.pages_scanned,
            "score": self.score,
            "summary": self.summary,
            "findings": [finding.to_dict() for finding in self.findings],
        }


def sort_findings(findings: list[Finding]) -> list[Finding]:
    """Сортирует находки: сначала по серьёзности, затем по правилу и странице."""
    return sorted(findings, key=lambda f: (f.severity.rank, f.rule, f.url, f.selector or ""))
