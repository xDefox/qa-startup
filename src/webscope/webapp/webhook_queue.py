"""In-memory queue for processing webhook events asynchronously.

Uses asyncio.Queue for simple in-memory processing.
For production with high load, consider Redis/RQ or Celery.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Callable, Awaitable

from .storage import Storage, Site
from webscope.watchdog import ChangeDetector, PageSnapshot

LOGGER = logging.getLogger("webscope.webhook_queue")


@dataclass
class WebhookEvent:
    """Событие от вебхука для обработки в фоне."""
    provider: str
    site_id: int
    deploy_url: str
    deploy_version: str | None = None
    deploy_commit: str | None = None
    raw_payload: dict | None = None


class WebhookQueue:
    """In-memory queue для обработки вебхуков в фоне."""

    def __init__(self, storage: Storage, max_size: int = 1000):
        self.storage = storage
        self.queue: asyncio.Queue[WebhookEvent] = asyncio.Queue(maxsize=max_size)
        self._worker_task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        """Запускает фоновый воркер."""
        if self._worker_task is None or self._worker_task.done():
            self._running = True
            self._worker_task = asyncio.create_task(self._worker())
            LOGGER.info("Webhook queue worker started")

    async def stop(self) -> None:
        """Останавливает фоновый воркер."""
        self._running = False
        if self._worker_task is not None:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None
        LOGGER.info("Webhook queue worker stopped")

    async def enqueue(self, event: WebhookEvent) -> bool:
        """Добавляет событие в очередь. Возвращает False если очередь полная."""
        try:
            self.queue.put_nowait(event)
            LOGGER.debug("Enqueued webhook event for site %d", event.site_id)
            return True
        except asyncio.QueueFull:
            LOGGER.warning("Webhook queue full, dropping event for site %d", event.site_id)
            return False

    async def _worker(self) -> None:
        """Фоновый воркер: обрабатывает события из очереди."""
        while self._running:
            try:
                event = await asyncio.wait_for(self.queue.get(), timeout=1.0)
                await self._process_event(event)
                self.queue.task_done()
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                LOGGER.exception("Error in webhook worker: %s", e)

    async def _process_event(self, event: WebhookEvent) -> None:
        """Обрабатывает одно событие вебхука."""
        try:
            site = self.storage.get_site(event.site_id)
            if not site:
                LOGGER.warning("Site %d not found for webhook event", event.site_id)
                return

            # Проверяем, включен ли Watchdog
            if not site.has_watchdog:
                LOGGER.info("Watchdog disabled for site %d, skipping", event.site_id)
                return

            # Определяем изменённые URL
            from ..watchdog import ChangeDetector
            detector = ChangeDetector(self.storage)

            # Получаем сохранённый снимок
            stored_snapshot = self.storage.get_site_snapshot(event.site_id)

            # Создаём текущий снимок (упрощённо - в полной реализации будет краулер)
            current_pages = {
                event.deploy_url: PageSnapshot(
                    url=event.deploy_url,
                    content_hash="",
                    etag=None,
                    last_modified=None,
                    status_code=200,
                )
            }

            added, changed, removed = detector.detect_changes(event.site_id, current_pages)
            changed_urls = changed + added

            if not changed_urls:
                LOGGER.info("No changes detected for site %d, skipping scan", event.site_id)
                return

            # Запускаем инкрементальный скан
            from ..scheduler import Monitor, ScanOptions
            from dataclasses import replace

            options = ScanOptions(
                max_pages=20,
                depth=2,
                timeout_ms=30000,
                allow_private=False,
                checks=["a11y", "console", "forms", "performance"],
                target_urls=changed_urls,
            )

            temp_monitor = Monitor(
                self.storage,
                options=options,
                scanner_func=self.storage.scanner_func if hasattr(self.storage, 'scanner_func') else None,
                notifier=None,
            )

            # Запускаем инкрементальный скан
            run = temp_monitor.begin(self.storage.get_site(event.site_id))
            run = temp_monitor.execute(self.storage.get_site(event.site_id), run)

            # Отправляем алерт если есть новые проблемы
            final_result = self.storage.finish_run(
                run.id,
                temp_monitor.scanner_func(event.deploy_url, ScanOptions(target_urls=changed_urls)).result
            )
            diff = self.storage.diff_with_previous(final_result)
            if diff and (diff.new_findings or diff.worsened_findings):
                # Отправляем алерт через notify
                from ..alerts import notify
                notify(
                    site_url=event.deploy_url,
                    diff=final_result.diff_with_previous if hasattr(final_result, 'diff_with_previous') else None,
                    email=None,  # TODO: брать из настроек сайта
                    telegram_chat=site.telegram_chat,
                )

            LOGGER.info("Processed webhook for site %d, scanned %d URLs", event.site_id, len(changed_urls))

        except Exception as e:
            LOGGER.exception("Error processing webhook event for site %d: %s", event.site_id, e)


async def create_webhook_queue(storage: Storage) -> WebhookQueue:
    """Фабричная функция для создания очереди вебхуков."""
    queue = WebhookQueue(storage)
    await queue.start()
    return queue