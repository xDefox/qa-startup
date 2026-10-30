"""Ограничитель частоты запусков проверок.

Один прогон — это браузер, обход до 20 страниц и десятки запросов. Без лимита
`curl` в цикле превращает сервис в генератор Chromium-процессов, поэтому у
запуска сканов есть два ограничения: сколько раз в минуту можно попросить
проверку с одного адреса и сколько прогонов может идти одновременно.

Лимитер в памяти процесса: для одного инстанса этого достаточно, для нескольких
воркеров нужен общий счётчик (Redis) — отмечено в README.
"""

from __future__ import annotations

import os
import threading
import time
from collections import defaultdict, deque

DEFAULT_LIMIT = 20
DEFAULT_WINDOW_SECONDS = 60.0
DEFAULT_MAX_CONCURRENT = 2


def _env_int(name: str, default: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def rate_limit() -> int:
    """Сколько запусков проверки разрешено с одного адреса за окно."""
    return _env_int("WEBSCOPE_RATE_LIMIT", DEFAULT_LIMIT)


def rate_window_seconds() -> float:
    return float(_env_int("WEBSCOPE_RATE_WINDOW", int(DEFAULT_WINDOW_SECONDS)))


def max_concurrent_scans() -> int:
    """Сколько прогонов может выполняться параллельно."""
    return _env_int("WEBSCOPE_MAX_CONCURRENT_SCANS", DEFAULT_MAX_CONCURRENT)


class RateLimiter:
    """Скользящее окно: не больше ``limit`` событий на ключ за ``window`` секунд."""

    def __init__(self, limit: int, window_seconds: float, clock=time.monotonic) -> None:
        self.limit = max(1, limit)
        self.window = max(1.0, float(window_seconds))
        self._clock = clock
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        """Пропускает событие и запоминает его, если лимит не исчерпан."""
        now = self._clock()
        with self._lock:
            events = self._events[key]
            boundary = now - self.window
            while events and events[0] < boundary:
                events.popleft()
            if len(events) >= self.limit:
                return False
            events.append(now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._events.clear()
