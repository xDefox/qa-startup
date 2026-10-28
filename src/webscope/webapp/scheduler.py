"""Планировщик регулярных проверок.

Работает как asyncio-таска рядом с веб-приложением: раз в ``check_interval``
секунд смотрит, каким сайтам пора делать прогон, и запускает проверки в фоне.
Проверка выполняется в отдельном потоке — синхронный Playwright нельзя
вызывать из потока с работающим event loop.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from ..models import ScanResult
from ..scanner import scan_site
from .alerts import notify
from .storage import Run, Site, Storage

LOGGER = logging.getLogger("webscope.scheduler")

SCHEDULES = {
    "off": 0,
    "daily": 1,
    "weekly": 7,
    "monthly": 30,
}


@dataclass
class ScanOptions:
    """Параметры проверки сайта для веб-версии."""

    max_pages: int = 20
    depth: int = 2
    timeout_ms: int = 30_000
    max_link_checks: int = 10
    allow_private: bool = False
    checks: list[str] | None = None


@dataclass
class CrawlOutcome:
    """Результат обхода: находки плюс техническая информация."""

    result: ScanResult
    pages_found: int = 0
    templates: int = 0
    extra: dict = field(default_factory=dict)


def default_scanner(url: str, options: ScanOptions) -> CrawlOutcome:
    """Стандартная проверка сайта: обход + проверка по одной странице шаблона."""
    import os

    allow_private = options.allow_private or os.environ.get("WEBSCOPE_ALLOW_PRIVATE") == "1"
    result, crawl_result = scan_site(
        url,
        max_pages=options.max_pages,
        max_depth=options.depth,
        timeout_ms=options.timeout_ms,
        max_link_checks=options.max_link_checks,
        allow_private=allow_private,
        checks=options.checks,
    )
    return CrawlOutcome(
        result=result,
        pages_found=len(crawl_result.pages),
        templates=len(crawl_result.templates),
    )


class Monitor:
    """Прогоняет проверки по сайтам и рассылает алерты о дельтах."""

    def __init__(
        self,
        storage: Storage,
        options: ScanOptions | None = None,
        *,
        scanner_func=default_scanner,
        notifier=None,
    ) -> None:
        self.storage = storage
        self.options = options or ScanOptions()
        self.scanner_func = scanner_func
        self.notifier = notifier or notify

    def schedule_next(self, site: Site) -> str | None:
        """Ставит дату следующего прогона по расписанию сайта."""
        days = SCHEDULES.get(site.schedule, 0)
        if days <= 0:
            self.storage.update_site(site.id, next_run_at=None)
            return None
        next_run = datetime.now(UTC) + timedelta(days=days)
        self.storage.update_site(site.id, next_run_at=next_run.isoformat())
        return next_run.isoformat()

    def begin(self, site: Site) -> Run:
        """Открывает прогон (строка в БД) и сразу переносит следующий запуск.

        Прогон открывается до самой проверки, чтобы веб-интерфейс сразу видел
        состояние «идёт проверка».
        """
        run = self.storage.start_run(site.id)
        self.schedule_next(site)
        return run

    def execute(self, site: Site, run: Run) -> Run:
        """Выполняет проверку, сохраняет результат, шлёт алерт о дельтах."""
        try:
            outcome = self.scanner_func(site.url, self.options)
        except Exception as exc:  # noqa: BLE001 - прогон не должен ронять планировщик
            LOGGER.warning("проверка %s не удалась: %s", site.url, exc)
            return self.storage.fail_run(run.id, f"{type(exc).__name__}: {exc}")

        stored = self.storage.finish_run(run.id, outcome.result)
        diff = self.storage.diff_with_previous(stored)
        # алертим и о новых проблемах, и о том, что старые стали серьёзнее:
        # регрессия без новых находок иначе остаётся незамеченной
        if diff is not None and (diff.new_findings or diff.worsened_findings):
            sent = self.notifier(
                site_url=site.url,
                diff=diff,
                email=site.email,
                telegram_chat=site.telegram_chat,
            )
            if sent:
                LOGGER.info("алерт по %s отправлен: %s", site.url, ", ".join(sent))
        return stored

    def run_site(self, site: Site) -> Run:
        """Полный цикл: открыть прогон → проверить → сохранить → сообщить."""
        return self.execute(site, self.begin(site))


class Scheduler:
    """Цикл: раз в ``check_interval`` секунд проверяет, кому пора запускаться."""

    def __init__(self, monitor: Monitor, storage: Storage, *, check_interval: int = 300) -> None:
        self.monitor = monitor
        self.storage = storage
        self.check_interval = check_interval
        self._task: asyncio.Task | None = None

    async def run_due(self) -> list[Run]:
        """Запускает проверки для сайтов, которым подошло время."""
        runs: list[Run] = []
        for site in self.storage.due_sites():
            runs.append(await asyncio.to_thread(self.monitor.run_site, site))
        return runs

    async def run_forever(self) -> None:
        while True:
            try:
                await self.run_due()
            except asyncio.CancelledError:
                raise
            except Exception:
                LOGGER.exception("ошибка в цикле планировщика")
            await asyncio.sleep(self.check_interval)

    def start(self) -> asyncio.Task:
        """Запускает фоновую задачу (если ещё не запущена)."""
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self.run_forever())
        return self._task

    async def stop(self) -> None:
        """Останавливает фоновую задачу."""
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
