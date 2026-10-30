"""Снимки, диффы и история прогонов.

Подписка возникает не на «сканировании», а на сравнении: «вчера было 12 проблем,
сегодня 15 — вот эти три новые». Здесь вся логика дельты.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
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

    @property
    def worsened_findings(self) -> list[DiffEntry]:
        """Старые проблемы, у которых серьёзность выросла (moderate → critical).

        Новых находок нет, но стало хуже — такой регрессии владелец не увидит
        сам, пока не зайдёт, поэтому алертим и об этом.
        """
        order = {severity.value: severity.rank for severity in Severity}
        result: list[DiffEntry] = []
        for entry in self.changed_findings:
            before = order.get(entry.severity_before or "", 99)
            after = order.get(entry.severity_after or "", 99)
            if after < before:
                result.append(entry)
        return result

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
    """Каталог истории сайта: читаемый slug + короткий хеш полного URL.

    Без хеша два разных URL с одинаковым началом (например, одинаковые первые
    120 символов у страниц с разными query-параметрами) попадали бы в один каталог.
    """
    cleaned = re.sub(r"[^a-zA-Z0-9.-]+", "_", url.strip()) or "site"
    digest = hashlib.sha1(url.strip().encode("utf-8")).hexdigest()[:8]
    return f"{cleaned[:100]}-{digest}"


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


def _element_key(finding: dict) -> tuple[str, str, str]:
    """Ключ элемента для сопоставления при нестабильных селекторах.

    Селектор может сдвинуться между прогонами (вставили баннер выше меню),
    хотя проблема осталась той же. Нормализованный HTML-фрагмент устойчив
    к таким сдвигам и не даёт диффу раздуть «новые/исправленные».
    """
    snippet = "".join((finding.get("snippet") or "").split())[:80].lower()
    return (finding.get("rule", ""), finding.get("url", ""), snippet)


def _changed_entry(old_item: dict, new_item: dict) -> DiffEntry:
    """Запись «серьёзность изменилась» для одной пары находок."""
    return DiffEntry(
        kind="changed",
        rule=new_item.get("rule", ""),
        title=new_item.get("title", ""),
        url=new_item.get("url", ""),
        selector=new_item.get("selector"),
        snippet=new_item.get("snippet"),
        severity_before=old_item.get("severity"),
        severity_after=new_item.get("severity"),
    )


def _new_entry(item: dict) -> DiffEntry:
    return DiffEntry(
        kind="new",
        rule=item.get("rule", ""),
        title=item.get("title", ""),
        url=item.get("url", ""),
        selector=item.get("selector"),
        snippet=item.get("snippet"),
        severity_after=item.get("severity"),
    )


def _fixed_entry(item: dict) -> DiffEntry:
    return DiffEntry(
        kind="fixed",
        rule=item.get("rule", ""),
        title=item.get("title", ""),
        url=item.get("url", ""),
        selector=item.get("selector"),
        snippet=item.get("snippet"),
        severity_before=item.get("severity"),
    )


def diff_snapshots(old: Snapshot, new: Snapshot) -> DiffReport:
    """Сравнивает два снимка: что появилось, что починено, что изменилось.

    Сопоставление двухфазное: сначала точное по (rule, url, selector), затем
    по нормализованному фрагменту элемента — чтобы сдвиг селекторов не выглядел
    как новая проблема плюс мгновенно «исправленная» старая.

    Обе фазы работают с мультимножествами: у документных правил (дубли id,
    отсутствие lang) селектора нет, и несколько разных дефектов дают одинаковый
    ключ. Раньше такой ключ схлопывался в dict, и новые находки пропадали
    из диффа — владелец не узнавал, что стало хуже.
    """
    report = DiffReport(
        url=new.url or old.url,
        old_at=old.taken_at,
        new_at=new.taken_at,
        score_before=old.score,
        score_after=new.score,
    )

    old_by_key: dict[tuple[str, str, str], list[int]] = defaultdict(list)
    for index, item in enumerate(old.findings):
        old_by_key[_key(item)].append(index)
    new_by_key: dict[tuple[str, str, str], list[int]] = defaultdict(list)
    for index, item in enumerate(new.findings):
        new_by_key[_key(item)].append(index)

    matched_old: set[int] = set()
    unmatched_new: list[int] = []

    # Фаза 1: точное совпадение по (rule, url, selector), по одному экземпляру.
    for key, new_indexes in new_by_key.items():
        old_indexes = old_by_key.get(key, [])
        for position, new_index in enumerate(new_indexes):
            if position >= len(old_indexes):
                unmatched_new.append(new_index)
                continue
            old_index = old_indexes[position]
            matched_old.add(old_index)
            if old.findings[old_index].get("severity") != new.findings[new_index].get("severity"):
                report.changed_findings.append(_changed_entry(old.findings[old_index], new.findings[new_index]))

    # Фаза 2: несопоставленные ищем по нормализованному фрагменту элемента.
    old_by_element: dict[tuple[str, str, str], list[int]] = defaultdict(list)
    for index, item in enumerate(old.findings):
        if index in matched_old:
            continue
        old_by_element[_element_key(item)].append(index)

    still_new: list[int] = []
    for new_index in unmatched_new:
        item = new.findings[new_index]
        candidates = old_by_element.get(_element_key(item)) or []
        if not candidates:
            still_new.append(new_index)
            continue
        old_index = candidates.pop(0)
        matched_old.add(old_index)
        if old.findings[old_index].get("severity") != item.get("severity"):
            report.changed_findings.append(_changed_entry(old.findings[old_index], item))

    report.new_findings = [_new_entry(new.findings[index]) for index in still_new]
    report.fixed_findings = [_fixed_entry(item) for index, item in enumerate(old.findings) if index not in matched_old]

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
