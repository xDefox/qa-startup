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

from ..auth_vault import decrypt as vault_decrypt
from ..auth_vault import encrypt as vault_encrypt
from ..history import DiffReport, Snapshot, diff_snapshots
from ..models import AuthCredentials, ScanResult, Severity
from ..models import Finding as ScanFinding

SCHEMA = """
CREATE TABLE IF NOT EXISTS sites (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    url             TEXT NOT NULL UNIQUE,
    email           TEXT,
    telegram_chat   TEXT,
    schedule        TEXT NOT NULL DEFAULT 'off',
    interval_days   INTEGER NOT NULL DEFAULT 7,
    next_run_at     TEXT,
    auth_kind       TEXT,
    auth_login      TEXT,
    auth_password   TEXT,
    auth_login_url  TEXT,
    organization_id INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL,
    watchdog_enabled INTEGER NOT NULL DEFAULT 0,
    watchdog_triggers TEXT,
    watchdog_webhook_secret TEXT,
    last_deploy_at TEXT,
    last_watchdog_check TEXT,
    last_watchdog_diff TEXT
);

CREATE TABLE IF NOT EXISTS organizations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    owner_email TEXT NOT NULL,
    created_at  TEXT NOT NULL
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
    snippet   TEXT,
    source    TEXT,
    help_url  TEXT,
    details   TEXT
);

CREATE INDEX IF NOT EXISTS idx_runs_site ON runs(site_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_findings_run ON findings(run_id);
"""

# Колонки, добавленные после первой публичной схемы: дозаполняем существующие базы.
# Формат: (таблица, колонка, тип).
_MIGRATIONS = (
    ("findings", "source", "TEXT"),
    ("findings", "help_url", "TEXT"),
    ("findings", "details", "TEXT"),
    ("sites", "auth_kind", "TEXT"),
    ("sites", "auth_login", "TEXT"),
    ("sites", "auth_password", "TEXT"),
    ("sites", "auth_login_url", "TEXT"),
)

# Миграция биллинга (Milestone 4): таблицы subscriptions + invoices.
# Добавляется отдельно, чтобы не ломать существующие базы без Stripe-интеграции.
BILLING_MIGRATION = """
CREATE TABLE IF NOT EXISTS subscriptions (
    site_id INTEGER PRIMARY KEY REFERENCES sites(id) ON DELETE CASCADE,
    plan TEXT NOT NULL DEFAULT 'free',
    status TEXT NOT NULL DEFAULT 'trial',
    started_at TEXT NOT NULL,
    trial_ends_at TEXT,
    current_period_ends_at TEXT,
    stripe_customer_id TEXT,
    stripe_subscription_id TEXT,
    payment_method TEXT
);
CREATE TABLE IF NOT EXISTS invoices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id INTEGER NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
    amount_cents INTEGER NOT NULL,
    currency TEXT NOT NULL DEFAULT 'USD',
    status TEXT NOT NULL DEFAULT 'draft',
    stripe_invoice_id TEXT,
    due_at TEXT,
    paid_at TEXT,
    pdf_url TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_subscriptions_site ON subscriptions(site_id);
CREATE INDEX IF NOT EXISTS idx_invoices_site ON invoices(site_id);
CREATE INDEX IF NOT EXISTS idx_invoices_status ON invoices(status);

CREATE TABLE IF NOT EXISTS scan_packages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    scans_total INTEGER NOT NULL,
    scans_used INTEGER NOT NULL DEFAULT 0,
    price_cents INTEGER NOT NULL,
    currency TEXT NOT NULL DEFAULT 'USD',
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    expires_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_scan_packages_org ON scan_packages(organization_id);
CREATE INDEX IF NOT EXISTS idx_scan_packages_status ON scan_packages(status);
"""


def _seal(password: str | None) -> str | None:
    """Шифрует пароль перед записью (без WEBSCOPE_AUTH_KEY — как есть)."""
    return vault_encrypt(password) if password else password


def _open(password: str | None) -> str | None:
    """Расшифровывает пароль из базы (старые записи — plaintext)."""
    return vault_decrypt(password) if password else password


def utcnow() -> datetime:
    return datetime.now(UTC)


def now_iso() -> str:
    return utcnow().isoformat()


@dataclass
class Site:
    """Сайт под наблюдением."""

    id: int = 0
    url: str = ""
    email: str | None = None
    telegram_chat: str | None = None
    schedule: str = "off"
    interval_days: int = 7
    next_run_at: str | None = None
    created_at: str = ""
    # авторизация на защищённом сайте: basic — заголовок, form — вход через форму
    auth_kind: str | None = None
    auth_login: str | None = None
    auth_password: str | None = None
    auth_login_url: str | None = None
    organization_id: int = 0
    # Watchdog
    watchdog_enabled: bool = False
    watchdog_triggers: list[str] = field(default_factory=lambda: ["webhook", "content_hash"])
    watchdog_webhook_secret: str | None = None
    # Watchdog status tracking
    last_deploy_at: str | None = None
    last_watchdog_check: str | None = None
    last_watchdog_diff: dict | None = None

    @property
    def has_auth(self) -> bool:
        """Настроен ли вход: есть механизм и логин."""
        return bool(self.auth_kind and self.auth_login)

    def auth_credentials(self) -> AuthCredentials | None:
        """Учётные данные для сканера (None — сайт проверяем без входа)."""
        if not self.has_auth:
            return None
        return AuthCredentials(
            kind=self.auth_kind or "basic",
            login=self.auth_login or "",
            password=self.auth_password or "",
            login_url=self.auth_login_url or None,
        )

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
            # пароль наружу не отдаём — только флаг "вход настроен"
            "has_auth": self.has_auth,
            "auth_kind": self.auth_kind if self.has_auth else None,
            "organization_id": self.organization_id,
            "watchdog_enabled": self.watchdog_enabled,
            "watchdog_triggers": self.watchdog_triggers,
            "watchdog_webhook_secret": self.watchdog_webhook_secret,
            "last_deploy_at": self.last_deploy_at,
            "last_watchdog_check": self.last_watchdog_check,
            "last_watchdog_diff": self.last_watchdog_diff,
        }

    @property
    def has_watchdog(self) -> bool:
        return self.watchdog_enabled and (self.watchdog_webhook_secret or "webhook" in self.watchdog_triggers)


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
    source: str = ""
    help_url: str | None = None
    details: dict = field(default_factory=dict)

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
            "source": self.source,
            "help_url": self.help_url,
            "details": self.details,
            "fp": self.details.get("fp", False),
        }

    @property
    def is_fp(self) -> bool:
        """Является ли находка ложным срабатыванием.

        Проверяет поле fp в details для обратной совместимости.
        """
        return self.details.get("fp", False)




@dataclass
class ScanPackage:
    """Пакет сканов (pay-per-scan)."""

    id: int
    organization_id: int
    scans_total: int
    scans_used: int = 0
    price_cents: int = 0
    currency: str = "USD"
    status: str = "active"
    created_at: str = ""
    expires_at: str | None = None

    @property
    def scans_left(self) -> int:
        return max(0, self.scans_total - self.scans_used)

    @property
    def is_active(self) -> bool:
        if self.status != "active":
            return False
        if self.scans_left <= 0:
            return False
        return True

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "scans_total": self.scans_total,
            "scans_used": self.scans_used,
            "scans_left": self.scans_left,
            "price_cents": self.price_cents,
            "currency": self.currency,
            "status": self.status,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "is_active": self.is_active,
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
        if str(self.path) != ":memory:":
            # WAL: планировщик и веб-хендлеры работают параллельно, лок-ошибок будет меньше.
            connection.execute("PRAGMA journal_mode = WAL")
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
            connection.executescript(BILLING_MIGRATION)
            self._migrate(connection)
            connection.commit()

    def _migrate(self, connection: sqlite3.Connection) -> None:
        """Дозаполняет схему старых баз новыми колонками (безопасно для существующих данных)."""
        for table in dict.fromkeys(table for table, _, _ in _MIGRATIONS):
            existing = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
            for mig_table, name, decl in _MIGRATIONS:
                if mig_table == table and name not in existing:
                    connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")

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
        auth_kind: str | None = None,
        auth_login: str | None = None,
        auth_password: str | None = None,
        auth_login_url: str | None = None,
    ) -> Site:
        """Создаёт сайт. Возвращает существующий, если URL уже известен."""
        with self._conn() as connection:
            existing = connection.execute("SELECT * FROM sites WHERE url = ?", (url,)).fetchone()
            if existing is not None:
                return _site_from_row(existing)
            cursor = connection.execute(
                "INSERT INTO sites (url, email, telegram_chat, schedule, interval_days,"
                " auth_kind, auth_login, auth_password, auth_login_url, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    url,
                    email,
                    telegram_chat,
                    schedule,
                    interval_days,
                    auth_kind,
                    auth_login,
                    _seal(auth_password),
                    auth_login_url,
                    now_iso(),
                ),
            )
            connection.commit()
            row = connection.execute("SELECT * FROM sites WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return _site_from_row(row)

    def get_site(self, site_id: int) -> Site | None:
        with self._conn() as connection:
            row = connection.execute("SELECT * FROM sites WHERE id = ?", (site_id,)).fetchone()
        return _site_from_row(row) if row else None

    def get_site_by_url(self, url: str) -> Site | None:
        """Найти сайт по URL."""
        with self._conn() as connection:
            row = connection.execute("SELECT * FROM sites WHERE url = ?", (url,)).fetchone()
        return _site_from_row(row) if row else None

    def list_sites(self) -> list[Site]:
        with self._conn() as connection:
            rows = connection.execute("SELECT * FROM sites ORDER BY id").fetchall()
        return [_site_from_row(row) for row in rows]

    def update_site(self, site_id: int, **fields) -> None:
        """Обновляет поля сайта (email, schedule, next_run_at, авторизация, watchdog и т.п.)."""
        allowed = {
            "email",
            "telegram_chat",
            "schedule",
            "interval_days",
            "next_run_at",
            "auth_kind",
            "auth_login",
            "auth_password",
            "auth_login_url",
            "watchdog_enabled",
            "watchdog_triggers",
            "watchdog_webhook_secret",
            "last_deploy_at",
            "last_watchdog_check",
            "last_watchdog_diff",
        }
        updates = {key: value for key, value in fields.items() if key in allowed}
        if "auth_password" in updates:
            updates["auth_password"] = _seal(updates["auth_password"])
        if "watchdog_triggers" in updates and isinstance(updates["watchdog_triggers"], list):
            updates["watchdog_triggers"] = ",".join(updates["watchdog_triggers"])
        if "last_watchdog_diff" in updates and isinstance(updates["last_watchdog_diff"], dict):
            import json
            updates["last_watchdog_diff"] = json.dumps(updates["last_watchdog_diff"])
        if not updates:
            return
        assignments = ", ".join(f"{key} = ?" for key in updates)
        with self._conn() as connection:
            connection.execute(
                f"UPDATE sites SET {assignments} WHERE id = ?",
                (*updates.values(), site_id),
            )
            connection.commit()

    def get_webhook_secret(self, provider: str) -> str | None:
        """Получает секрет вебхука для провайдера (пока используем общий секрет сайта)."""
        # В будущем можно добавить отдельную таблицу для секретов по провайдерам
        # Пока используем общий секрет сайта
        return None  # TODO: реализовать хранение секретов по провайдерам

    def delete_site(self, site_id: int) -> bool:
        """Удаляет сайт вместе с прогонами и находками (каскад по FK)."""
        with self._conn() as connection:
            cursor = connection.execute("DELETE FROM sites WHERE id = ?", (site_id,))
            connection.commit()
            return cursor.rowcount > 0

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
                "INSERT INTO findings (run_id, rule, severity, title, message, url, selector, snippet,"
                " source, help_url, details)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                        finding.source,
                        finding.help_url,
                        json.dumps(finding.details, ensure_ascii=False) if finding.details else None,
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
        """Последний успешный прогон — на нём строится отчёт.

        Запрос идёт по всей истории, а не по последним 20 строкам: после череды
        неудачных прогонов (сайт лежал) отчёт исчезал из интерфейса, хотя он есть.
        """
        with self._conn() as connection:
            row = connection.execute(
                "SELECT * FROM runs WHERE site_id = ? AND status = 'ok' ORDER BY id DESC LIMIT 1",
                (site_id,),
            ).fetchone()
        return _run_from_row(row) if row else None

    def count_running(self) -> int:
        """Сколько прогонов выполняется прямо сейчас (для ограничения нагрузки)."""
        with self._conn() as connection:
            row = connection.execute("SELECT COUNT(*) AS total FROM runs WHERE status = 'running'").fetchone()
        return int(row["total"] or 0)

    def reconcile_running(self, error: str = "прогон прерван: приложение перезапустилось") -> int:
        """Закрывает прогоны, оставшиеся 'running' после падения процесса.

        Такие сироты иначе вечно висят «проверка выполняется» на главной и
        навсегда съедают лимит count_running() — после 3–4 рестартов мониторинг
        перестаёт запускаться вообще. Возвращает число закрытых прогонов.
        """
        with self._conn() as connection:
            cursor = connection.execute(
                "UPDATE runs SET status = 'error', finished_at = ?, error = ? WHERE status = 'running'",
                (now_iso(), error[:2000]),
            )
            connection.commit()
            return int(cursor.rowcount or 0)

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
        return [_finding_from_row(row) for row in rows]

    def mark_finding_fp(self, finding_id: int, fp: bool = True) -> None:
        """Помечает находку как ложную (FP) или снимает пометку."""
        with self._conn() as connection:
            row = connection.execute("SELECT details FROM findings WHERE id = ?", (finding_id,)).fetchone()
            if row is None:
                return
            details = json.loads(row["details"] or "{}")
            details["fp"] = fp
            connection.execute(
                "UPDATE findings SET details = ? WHERE id = ?",
                (json.dumps(details, ensure_ascii=False), finding_id),
            )
            connection.commit()

    def findings_as_models(self, run_id: int) -> list[ScanFinding]:
        """Находки прогона в виде моделей движка — чтобы переиспользовать scoring."""
        result: list[ScanFinding] = []
        for row in self.findings_of(run_id):
            try:
                severity = Severity(row.severity)
            except ValueError:
                severity = Severity.MODERATE
            finding = ScanFinding(
                rule=row.rule,
                severity=severity,
                title=row.title,
                message=row.message,
                url=row.url,
                selector=row.selector,
                snippet=row.snippet,
                help_url=row.help_url,
                source=row.source or "webscope",
                details=row.details,
            )
            finding.id = row.id
            result.append(finding)
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


    # --- Scan Packages (Pay-per-scan) ---
    def create_scan_package(self, organization_id: int, scans_total: int, price_cents: int, currency: str = "USD") -> ScanPackage:
        """Создаёт новый пакет сканов."""
        now = now_iso()
        with self._conn() as conn:
            cursor = conn.execute(
                """INSERT INTO scan_packages (
                    organization_id, scans_total, scans_used, price_cents, currency, status, created_at
                ) VALUES (?, ?, 0, ?, ?, "active", ?)""",
                (organization_id, scans_total, price_cents, currency, now),
            )
            conn.commit()
            pkg_id = cursor.lastrowid
        return self.get_scan_package(pkg_id)

    def get_scan_package(self, package_id: int) -> ScanPackage | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM scan_packages WHERE id = ?", (package_id,)
            ).fetchone()
        if not row:
            return None
        return ScanPackage(
            id=row["id"],
            organization_id=row["organization_id"],
            scans_total=row["scans_total"],
            scans_used=row["scans_used"],
            price_cents=row["price_cents"],
            currency=row["currency"],
            status=row["status"],
            created_at=row["created_at"],
            expires_at=row["expires_at"] if "expires_at" in row.keys() else None,
        )

    def list_scan_packages(self, organization_id: int, active_only: bool = True) -> list[ScanPackage]:
        with self._conn() as conn:
            if active_only:
                rows = conn.execute(
                    "SELECT * FROM scan_packages WHERE organization_id = ? AND status = 'active' ORDER BY created_at DESC",
                    (organization_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM scan_packages WHERE organization_id = ? ORDER BY created_at DESC",
                    (organization_id,),
                ).fetchall()
        packages = []
        for row in rows:
            packages.append(ScanPackage(
                id=row["id"],
                organization_id=row["organization_id"],
                scans_total=row["scans_total"],
                scans_used=row["scans_used"],
                price_cents=row["price_cents"],
                currency=row["currency"],
                status=row["status"],
                created_at=row["created_at"],
                expires_at=row["expires_at"] if "expires_at" in row.keys() else None,
            ))
        return packages

    def consume_scan(self, package_id: int) -> ScanPackage | None:
        """Списывает один скан из пакета. Возвращает обновлённый пакет или None, если неактивен."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM scan_packages WHERE id = ?", (package_id,)
            ).fetchone()
            if not row:
                return None
            pkg = ScanPackage(
                id=row["id"],
                organization_id=row["organization_id"],
                scans_total=row["scans_total"],
                scans_used=row["scans_used"],
                price_cents=row["price_cents"],
                currency=row["currency"],
                status=row["status"],
                created_at=row["created_at"],
                expires_at=row["expires_at"] if "expires_at" in row.keys() else None,
            )
            if not pkg.is_active:
                return None
            new_used = pkg.scans_used + 1
            new_status = 'active'
            if new_used >= pkg.scans_total:
                new_status = "exhausted"
            conn.execute(
                "UPDATE scan_packages SET scans_used = ?, status = ? WHERE id = ?",
                (new_used, new_status, package_id),
            )
            conn.commit()
            pkg.scans_used = new_used
            pkg.status = new_status
            return pkg

    def get_active_package_for_org(self, organization_id: int) -> ScanPackage | None:
        """Возвращает первый активный пакет с оставшимися сканами для организации."""
        packages = self.list_scan_packages(organization_id, active_only=True)
        for pkg in packages:
            if pkg.is_active:
                return pkg
            return None




    # --- Site Snapshots (Watchdog) ---
    # --- Site Snapshots (Watchdog) ---
    def save_site_snapshot(self, site_id: int, url: str, pages_data: dict, sitemap_urls: list[str] | None = None) -> None:
        """Сохраняет снимок сайта для детекции изменений."""
        import json
        snapshot_data = {
            "site_id": site_id,
            "url": url,
            "pages": pages_data,
            "sitemap_urls": sitemap_urls or [],
            "fetched_at": datetime.now(UTC).isoformat(),
        }
        with self._conn() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS site_snapshots (
                    site_id INTEGER PRIMARY KEY REFERENCES sites(id) ON DELETE CASCADE,
                    url TEXT NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )""",
            )
            conn.execute(
                """INSERT INTO site_snapshots (site_id, url, snapshot_json, updated_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(site_id) DO UPDATE SET
                       url = excluded.url,
                       snapshot_json = excluded.snapshot_json,
                       updated_at = excluded.updated_at""",
                (site_id, url, json.dumps(snapshot_data), datetime.now(UTC).isoformat()),
            )
            conn.commit()

    def get_site_snapshot(self, site_id: int) -> dict | None:
        """Получает сохранённый снимок сайта."""
        with self._conn() as conn:
            # Проверяем, существует ли таблица
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='site_snapshots'"
            ).fetchone()
            if not row:
                return None
            row = conn.execute(
                "SELECT snapshot_json FROM site_snapshots WHERE site_id = ?",
                (site_id,),
            ).fetchone()
        if not row:
            return None
        import json
        try:
            return json.loads(row["snapshot_json"])
        except json.JSONDecodeError:
            return None

    def delete_site_snapshot(self, site_id: int) -> None:
        """Удаляет снимок сайта."""
        with self._conn() as conn:
            conn.execute("DELETE FROM site_snapshots WHERE site_id = ?", (site_id,))
            conn.commit()



def _finding_from_row(row: sqlite3.Row) -> Finding:
    details: dict = {}
    # колонки добавлены миграцией: у старых БД их может не быть в результате
    keys = row.keys()
    raw_details = row["details"] if "details" in keys else None
    if raw_details:
        try:
            details = json.loads(raw_details)
        except json.JSONDecodeError:
            details = {}
    return Finding(
        id=row["id"],
        run_id=row["run_id"],
        rule=row["rule"],
        severity=row["severity"],
        title=row["title"] or "",
        message=row["message"] or "",
        url=row["url"] or "",
        selector=row["selector"],
        snippet=row["snippet"],
        source=(row["source"] or "") if "source" in keys else "",
        help_url=row["help_url"] if "help_url" in keys else None,
        details=details,
    )


def _site_from_row(row: sqlite3.Row) -> Site:
    keys = row.keys()
    return Site(
        id=row["id"],
        url=row["url"],
        email=row["email"],
        telegram_chat=row["telegram_chat"],
        schedule=row["schedule"],
        interval_days=row["interval_days"],
        next_run_at=row["next_run_at"],
        created_at=row["created_at"],
        # колонок авторизации может не быть в старых базах — миграция их добавит,
        # но на случай чтения до неё проверяем по именам
        auth_kind=row["auth_kind"] if "auth_kind" in keys else None,
        auth_login=row["auth_login"] if "auth_login" in keys else None,
        auth_password=_open(row["auth_password"]) if "auth_password" in keys else None,
        auth_login_url=row["auth_login_url"] if "auth_login_url" in keys else None,
        organization_id=row["organization_id"] if "organization_id" in keys else 0,
        # Watchdog
        watchdog_enabled=bool(row["watchdog_enabled"]) if "watchdog_enabled" in keys else False,
        watchdog_triggers=row["watchdog_triggers"].split(",") if "watchdog_triggers" in keys and row["watchdog_triggers"] else ["webhook", "content_hash"],
        watchdog_webhook_secret=row["watchdog_webhook_secret"] if "watchdog_webhook_secret" in keys else None,
        # Watchdog status tracking
        last_deploy_at=row["last_deploy_at"] if "last_deploy_at" in keys else None,
        last_watchdog_check=row["last_watchdog_check"] if "last_watchdog_check" in keys else None,
        last_watchdog_diff=json.loads(row["last_watchdog_diff"]) if "last_watchdog_diff" in keys and row["last_watchdog_diff"] else None,
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
