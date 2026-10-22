"""Снимки, диффы и история прогонов.

Подписка возникает не на «сканировании», а на сравнении: «вчера было 12 проблем,
сегодня 15 — вот эти три новые». Здесь вся логика дельты.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from .models import ScanResult, Severity
from .scoring import compute_score

SCHEMA_VERSION = "1.0"


@dataclass
class Snapshot:
    """Снимок состояния сайта в конкретный момент."""

    url: str
    taken_at: str
    score: int
    pages_scanned: int = 0
    findings: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "url": self.url,
            "taken_at": self.taken_at,
            "score": self.score,
            "pages_scanned": self.pages_scanned,
            "findings": self.findings,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Snapshot:
        return cls(
            url=data.get("url", ""),
            taken_at=data.get("taken_at", ""),
            score=int(data.get("score", 100)),
            pages_scanned=int(data.get("pages_scanned", 0)),
            findings=list(data.get("findings", [])),
        )


@dataclass
class DiffEntry:
    """Одно изменение между снимками."""

    kind: str  # new | fixed | changed
    rule: str
    title: str
    url: str
    selector: str | None = None
    snippet: str | None = None
    severity_before: str | None = None
    severity_after: str | None = None

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "rule": self.rule,
            "title": self.title,
            "url": self.url,
            "selector": self.selector,
            "snippet": self.snippet,
            "severity_before": self.severity_before,
            "severity_after": self.severity_after,
        }


@dataclass
class DiffReport:
    """Сравнение двух снимков."""

    url: str
    old_at: str = ""
    new_at: str = ""
    score_before: int = 100
    score_after: int = 100
    new_findings: list[DiffEntry] = field(default_factory=list)
    fixed_findings: list[DiffEntry] = field(default_factory=list)
    changed_findings: list[DiffEntry] = field(default_factory=list)

    @property
    def is_improvement(self) -> bool:
        return self.score_after > self.score_before

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "old_at": self.old_at,
            "new_at": self.new_at,
            "score_before": self.score_before,
            "score_after": self.score_after,
            "delta": self.score_after - self.score_before,
            "new_findings": [entry.to_dict() for entry in self.new_findings],
            "fixed_findings": [entry.to_dict() for entry in self.fixed_findings],
            "changed_findings": [entry.to_dict() for entry in self.changed_findings],
            "summary": {
                "new": len(self.new_findings),
                "fixed": len(self.fixed_findings),
                "changed": len(self.changed_findings),
            },
        }


def _slug(url: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9.-]+", "_", url.strip()) or "site"
    return cleaned[:120]


def snapshot_from_result(result: ScanResult) -> Snapshot:
    """Собирает снимок из результата сканирования."""
    return Snapshot(
        url=result.final_url or result.url,
        taken_at=result.generated_at,
        score=compute_score(result.findings),
        pages_scanned=result.pages_scanned,
        findings=[finding.to_dict() for finding in result.findings],
    )


def history_dir_for(base: Path, url: str) -> Path:
    """Каталог истории для конкретного сайта."""
    return base / _slug(url)


def save_snapshot(snapshot: Snapshot, base: Path, *, make_latest: bool = True) -> Path:
    """Сохраняет снимок в историю и возвращает путь к файлу."""
    directory = history_dir_for(base, snapshot.url)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
    path = directory / f"{stamp}.json"
    path.write_text(json.dumps(snapshot.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    if make_latest:
        (directory / "latest.json").write_text(
            json.dumps(snapshot.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return path


def load_snapshot(path: Path) -> Snapshot:
    """Читает снимок из файла."""
    return Snapshot.from_dict(json.loads(path.read_text(encoding="utf-8")))


def list_snapshots(base: Path, url: str | None = None) -> list[Path]:
    """Список снимков, отсортированный по времени (старые → новые)."""
    if url is not None:
        directories = [history_dir_for(base, url)]
    else:
        directories = [path for path in sorted(base.glob("*")) if path.is_dir()]

    snapshots: list[Path] = []
    for directory in directories:
        if not directory.exists():
            continue
        snapshots.extend(sorted(path for path in directory.glob("*.json") if path.name != "latest.json"))
    return snapshots


def _key(finding: dict) -> tuple[str, str, str]:
    return (finding.get("rule", ""), finding.get("url", ""), finding.get("selector") or "")


def diff_snapshots(old: Snapshot, new: Snapshot) -> DiffReport:
    """Сравнивает два снимка: что появилось, что починено, что изменилось."""
    old_by_key = {_key(item): item for item in old.findings}
    new_by_key = {_key(item): item for item in new.findings}

    report = DiffReport(
        url=new.url or old.url,
        old_at=old.taken_at,
        new_at=new.taken_at,
        score_before=old.score,
        score_after=new.score,
    )

    for key, finding in new_by_key.items():
        if key not in old_by_key:
            report.new_findings.append(
                DiffEntry(
                    kind="new",
                    rule=finding.get("rule", ""),
                    title=finding.get("title", ""),
                    url=finding.get("url", ""),
                    selector=finding.get("selector"),
                    snippet=finding.get("snippet"),
                    severity_after=finding.get("severity"),
                )
            )
        elif old_by_key[key].get("severity") != finding.get("severity"):
            report.changed_findings.append(
                DiffEntry(
                    kind="changed",
                    rule=finding.get("rule", ""),
                    title=finding.get("title", ""),
                    url=finding.get("url", ""),
                    selector=finding.get("selector"),
                    snippet=finding.get("snippet"),
                    severity_before=old_by_key[key].get("severity"),
                    severity_after=finding.get("severity"),
                )
            )

    for key, finding in old_by_key.items():
        if key not in new_by_key:
            report.fixed_findings.append(
                DiffEntry(
                    kind="fixed",
                    rule=finding.get("rule", ""),
                    title=finding.get("title", ""),
                    url=finding.get("url", ""),
                    selector=finding.get("selector"),
                    snippet=finding.get("snippet"),
                    severity_before=finding.get("severity"),
                )
            )

    order = {severity.value: severity.rank for severity in Severity}
    report.new_findings.sort(key=lambda entry: (order.get(entry.severity_after or "", 99), entry.rule))
    report.fixed_findings.sort(key=lambda entry: (order.get(entry.severity_before or "", 99), entry.rule))
    report.changed_findings.sort(key=lambda entry: entry.rule)
    return report


def latest_snapshot(base: Path, url: str) -> Snapshot | None:
    """Последний снимок по сайту (если есть)."""
    path = history_dir_for(base, url) / "latest.json"
    if not path.exists():
        return None
    return load_snapshot(path)


def trend(base: Path, url: str) -> list[dict]:
    """Ряд динамики: список прогонов с баллами и количеством находок."""
    points: list[dict] = []
    for path in list_snapshots(base, url):
        snapshot = load_snapshot(path)
        counts = {severity.value: 0 for severity in Severity}
        for finding in snapshot.findings:
            severity = finding.get("severity", "minor")
            if severity in counts:
                counts[severity] += 1
        points.append(
            {
                "taken_at": snapshot.taken_at,
                "score": snapshot.score,
                "pages_scanned": snapshot.pages_scanned,
                **counts,
                "total": len(snapshot.findings),
            }
        )
    return points
