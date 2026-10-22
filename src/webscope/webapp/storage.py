"""Хранилище SQLite: сайты, прогоны, находки.

Отдельный слой от движка: движок ничего не знает про базу, хранилище ничего
не знает про браузер. Связка — один вызов ``scan_site`` + ``finish_run``.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from ..history import DiffReport, Snapshot, diff_snapshots
from ..models import Finding as ScanFinding
from ..models import ScanResult, Severity

SCHEMA = """
CREATE TABLE IF NOT EXISTS sites (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    url             TEXT NOT NULL UNIQUE,
    email           TEXT,
    telegram_chat   TEXT,
    schedule        TEXT NOT NULL DEFAULT 'off',
    interval_days   INTEGER NOT NULL DEFAULT 7,
    next_run_at     TEXT,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id       INTEGER NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    status        TEXT NOT NULL DEFAULT 'running',
    score         INTEGER,
    pages_scanned INTEGER NOT NULL DEFAULT 0,
    duration_ms   INTEGER NOT NULL DEFAULT 0,
    error         TEXT,
    raw           TEXT
);

CREATE TABLE IF NOT EXISTS findings (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id    INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    rule      TEXT NOT NULL,
    severity  TEXT NOT NULL,
    title     TEXT,
    message   TEXT,
    url       TEXT,
    selector  TEXT,
    snippet   TEXT
);

CREATE INDEX IF NOT EXISTS idx_runs_site ON runs(site_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_findings_run ON findings(run_id);
"""


def utcnow() -> datetime:
    return datetime.now(UTC)


def now_iso() -> str:
    return utcnow().isoformat()


@dataclass
class Site:
    """Сайт под наблюдением."""

    id: int
    url: str
    email: str | None = None
    telegram_chat: str | None = None
    schedule: str = "off"
    interval_days: int = 7
    next_run_at: str | None = None
    created_at: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "url": self.url,
            "email": self.email,
            "telegram_chat": self.telegram_chat,
            "schedule": self.schedule,
            "interval_days": self.interval_days,
            "next_run_at": self.next_run_at,
            "created_at": self.created_at,
        }


@dataclass
class Run:
    """Один прогон проверки по сайту."""

    id: int
    site_id: int
    started_at: str
    finished_at: str | None = None
    status: str = "running"
    score: int | None = None
    pages_scanned: int = 0
    duration_ms: int = 0
    error: str | None = None
    raw: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "site_id": self.site_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "status": self.status,
            "score": self.score,
            "pages_scanned": self.pages_scanned,
            "duration_ms": self.duration_ms,
            "error": self.error,
        }


@dataclass
class Finding:
    """Находка в привязке к прогону."""

    id: int
    run_id: int
    rule: str
    severity: str
    title: str = ""
    message: str = ""
    url: str = ""
    selector: str | None = None
    snippet: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "run_id": self.run_id,
            "rule": self.rule,
            "severity": self.severity,
            "title": self.title,
            "message": self.message,
            "url": self.url,
            "selector": self.selector,
            "snippet": self.snippet,
        }


class Storage:
    """Тонкая обёртка над SQLite. Одно соединение на операцию — без блокировок."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._shared: sqlite3.Connection | None = None
        if str(self.path) == ":memory:":
            # Одно соединение на весь процесс, иначе данные исчезают между операциями.
            self._shared = self._connect()
        self.init_db()

    # --- соединения ---

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.path), check_same_thread=False, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        if self._shared is not None:
            yield self._shared
            return
        connection = self._connect()
        try:
            yield connection
        finally:
            connection.close()

    def init_db(self) -> None:
        with self._conn() as connection:
            connection.executescript(SCHEMA)
            connection.commit()

    def close(self) -> None:
        if self._shared is not None:
            self._shared.close()
            self._shared = None

    # --- сайты ---

    def add_site(
        self,
        url: str,
        *,
        email: str | None = None,
        telegram_chat: str | None = None,
        schedule: str = "off",
        interval_days: int = 7,
    ) -> Site:
        """Создаёт сайт. Возвращает существующий, если URL уже известен."""
        with self._conn() as connection:
            existing = connection.execute("SELECT * FROM sites WHERE url = ?", (url,)).fetchone()
            if existing is not None:
                return _site_from_row(existing)
            cursor = connection.execute(
                "INSERT INTO sites (url, email, telegram_chat, schedule, interval_days, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (url, email, telegram_chat, schedule, interval_days, now_iso()),
            )
            connection.commit()
            row = connection.execute("SELECT * FROM sites WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return _site_from_row(row)

    def get_site(self, site_id: int) -> Site | None:
        with self._conn() as connection:
            row = connection.execute("SELECT * FROM sites WHERE id = ?", (site_id,)).fetchone()
        return _site_from_row(row) if row else None

    def list_sites(self) -> list[Site]:
        with self._conn() as connection:
            rows = connection.execute("SELECT * FROM sites ORDER BY id").fetchall()
        return [_site_from_row(row) for row in rows]

    def update_site(self, site_id: int, **fields) -> None:
        """Обновляет поля сайта (email, schedule, next_run_at и т.п.)."""
        allowed = {"email", "telegram_chat", "schedule", "interval_days", "next_run_at"}
        updates = {key: value for key, value in fields.items() if key in allowed}
        if not updates:
            return
        assignments = ", ".join(f"{key} = ?" for key in updates)
        with self._conn() as connection:
            connection.execute(
                f"UPDATE sites SET {assignments} WHERE id = ?",
                (*updates.values(), site_id),
            )
            connection.commit()

    # --- прогоны ---

    def start_run(self, site_id: int) -> Run:
        with self._conn() as connection:
            cursor = connection.execute(
                "INSERT INTO runs (site_id, started_at, status) VALUES (?, ?, 'running')",
                (site_id, now_iso()),
            )
            connection.commit()
            row = connection.execute("SELECT * FROM runs WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return _run_from_row(row)

    def finish_run(self, run_id: int, result: ScanResult) -> Run:
        """Сохраняет результат прогона вместе с находками."""
        raw = json.dumps(result.to_dict(), ensure_ascii=False)
        with self._conn() as connection:
            connection.execute(
                "UPDATE runs SET status = 'ok', finished_at = ?, score = ?, pages_scanned = ?,"
                " duration_ms = ?, raw = ? WHERE id = ?",
                (
                    now_iso(),
                    result.score,
                    result.pages_scanned,
                    result.duration_ms,
                    raw,
                    run_id,
                ),
            )
            connection.executemany(
                "INSERT INTO findings (run_id, rule, severity, title, message, url, selector, snippet)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        run_id,
                        finding.rule,
                        finding.severity.value,
                        finding.title,
                        finding.message,
                        finding.url,
                        finding.selector,
                        finding.snippet,
                    )
                    for finding in result.findings
                ],
            )
            connection.commit()
            row = connection.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        return _run_from_row(row)

    def fail_run(self, run_id: int, error: str) -> Run:
        with self._conn() as connection:
            connection.execute(
                "UPDATE runs SET status = 'error', finished_at = ?, error = ? WHERE id = ?",
                (now_iso(), error[:2000], run_id),
            )
            connection.commit()
            row = connection.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        return _run_from_row(row)

    def get_run(self, run_id: int) -> Run | None:
        with self._conn() as connection:
            row = connection.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        return _run_from_row(row) if row else None

    def list_runs(self, site_id: int, limit: int = 30) -> list[Run]:
        with self._conn() as connection:
            rows = connection.execute(
                "SELECT * FROM runs WHERE site_id = ? ORDER BY id DESC LIMIT ?", (site_id, limit)
            ).fetchall()
        return [_run_from_row(row) for row in rows]

    def latest_run(self, site_id: int, *, finished_only: bool = True) -> Run | None:
        runs = self.list_runs(site_id, limit=20)
        for run in runs:
            if finished_only and run.status == "running":
                continue
            return run
        return runs[0] if runs else None

    def latest_ok_run(self, site_id: int) -> Run | None:
        """Последний успешный прогон — на нём строится отчёт."""
        for run in self.list_runs(site_id, limit=20):
            if run.status == "ok":
                return run
        return None

    def running_run(self, site_id: int) -> Run | None:
        """Прогон, который сейчас выполняется (если он есть)."""
        with self._conn() as connection:
            row = connection.execute(
                "SELECT * FROM runs WHERE site_id = ? AND status = 'running' ORDER BY id DESC LIMIT 1",
                (site_id,),
            ).fetchone()
        return _run_from_row(row) if row else None

    def previous_run(self, site_id: int, before_run_id: int) -> Run | None:
        """Последний завершённый прогон, который был раньше указанного."""
        with self._conn() as connection:
            row = connection.execute(
                "SELECT * FROM runs WHERE site_id = ? AND id < ? AND status = 'ok' ORDER BY id DESC LIMIT 1",
                (site_id, before_run_id),
            ).fetchone()
        return _run_from_row(row) if row else None

    def findings_of(self, run_id: int) -> list[Finding]:
        with self._conn() as connection:
            rows = connection.execute("SELECT * FROM findings WHERE run_id = ? ORDER BY id", (run_id,)).fetchall()
        return [
            Finding(
                id=row["id"],
                run_id=row["run_id"],
                rule=row["rule"],
                severity=row["severity"],
                title=row["title"] or "",
                message=row["message"] or "",
                url=row["url"] or "",
                selector=row["selector"],
                snippet=row["snippet"],
            )
            for row in rows
        ]

    def findings_as_models(self, run_id: int) -> list[ScanFinding]:
        """Находки прогона в виде моделей движка — чтобы переиспользовать scoring."""
        result: list[ScanFinding] = []
        for row in self.findings_of(run_id):
            try:
                severity = Severity(row.severity)
            except ValueError:
                severity = Severity.MODERATE
            result.append(
                ScanFinding(
                    rule=row.rule,
                    severity=severity,
                    title=row.title,
                    message=row.message,
                    url=row.url,
                    selector=row.selector,
                    snippet=row.snippet,
                )
            )
        return result

    def severity_counts(self, run_ids: list[int]) -> dict[int, dict[str, int]]:
        """Сколько находок каждой серьёзности в каждом из прогонов."""
        counts: dict[int, dict[str, int]] = {}
        if not run_ids:
            return counts
        placeholders = ",".join("?" for _ in run_ids)
        query = (
            "SELECT run_id, severity, COUNT(*) AS total FROM findings"
            f" WHERE run_id IN ({placeholders}) GROUP BY run_id, severity"
        )
        with self._conn() as connection:
            rows = connection.execute(query, run_ids).fetchall()
        for row in rows:
            bucket = counts.setdefault(row["run_id"], {})
            bucket[row["severity"]] = row["total"]
        return counts

    # --- диффы ---

    def snapshot_of(self, run: Run) -> Snapshot:
        """Собирает снимок из прогона — тот же формат, что у файловой истории."""
        raw = run.raw or {}
        findings = [
            {
                "rule": finding.rule,
                "severity": finding.severity,
                "title": finding.title,
                "message": finding.message,
                "url": finding.url,
                "selector": finding.selector,
                "snippet": finding.snippet,
            }
            for finding in self.findings_of(run.id)
        ]
        return Snapshot(
            url=raw.get("url", ""),
            taken_at=run.finished_at or run.started_at,
            score=run.score if run.score is not None else 100,
            pages_scanned=run.pages_scanned,
            findings=findings,
        )

    def diff_runs(self, old_run: Run, new_run: Run) -> DiffReport:
        """Сравнивает два прогона по правилам diff_snapshots."""
        return diff_snapshots(self.snapshot_of(old_run), self.snapshot_of(new_run))

    def diff_with_previous(self, run: Run) -> DiffReport | None:
        """Дифф текущего прогона с предыдущим успешным."""
        current = self.get_run(run.id) or run
        previous = self.previous_run(current.site_id, current.id)
        if previous is None:
            return None
        return self.diff_runs(previous, current)

    # --- планировщик ---

    def due_sites(self, limit: int = 5) -> list[Site]:
        """Сайты, которым пора делать следующий прогон."""
        stamp = now_iso()
        with self._conn() as connection:
            rows = connection.execute(
                "SELECT * FROM sites WHERE schedule != 'off' AND next_run_at IS NOT NULL"
                " AND next_run_at <= ? ORDER BY next_run_at LIMIT ?",
                (stamp, limit),
            ).fetchall()
        return [_site_from_row(row) for row in rows]

    def mark_scheduled(self, site_id: int, next_run_at: str) -> None:
        self.update_site(site_id, next_run_at=next_run_at)


def _site_from_row(row: sqlite3.Row) -> Site:
    return Site(
        id=row["id"],
        url=row["url"],
        email=row["email"],
        telegram_chat=row["telegram_chat"],
        schedule=row["schedule"],
        interval_days=row["interval_days"],
        next_run_at=row["next_run_at"],
        created_at=row["created_at"],
    )


def _run_from_row(row: sqlite3.Row) -> Run:
    raw: dict = {}
    if row["raw"]:
        try:
            raw = json.loads(row["raw"])
        except json.JSONDecodeError:
            raw = {}
    return Run(
        id=row["id"],
        site_id=row["site_id"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        status=row["status"],
        score=row["score"],
        pages_scanned=row["pages_scanned"],
        duration_ms=row["duration_ms"],
        error=row["error"],
        raw=raw,
    )


def runs_to_rows(runs: Iterable[Run]) -> list[dict]:
    return [run.to_dict() for run in runs]
