"""Состояние приложения: то, что раньше жило в замыканиях `create_app`.

Маршруты вынесены в отдельные модули, поэтому им нужен способ добраться до
хранилища, монитора, шаблонов и лимитера. Состояние лежит в `app.state` под
одним ключом и достаётся зависимостью `get_state` — маршрут не знает, как
приложение собрано, и его можно проверить отдельно.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates

from .limits import RateLimiter
from .scheduler import Monitor, ScanOptions, Scheduler
from .storage import Storage

# Ключ в app.state: одно место, а не набор app.state.storage / .monitor / ...
STATE_KEY = "webscope"


@dataclass
class AppState:
    """Всё, что нужно маршруту, чтобы обработать запрос."""

    storage: Storage
    monitor: Monitor
    scheduler: Scheduler
    templates: Jinja2Templates
    limiter: RateLimiter
    scan_options: ScanOptions
    local_dir: Path
    # фоновые задачи прогонов, запущенных без BackgroundTasks
    tasks: set[asyncio.Task] = field(default_factory=set)


def get_state(request: Request) -> AppState:
    """Зависимость FastAPI: состояние текущего приложения."""
    state = getattr(request.app.state, STATE_KEY, None)
    if state is None:  # приложение собрано не через create_app
        raise RuntimeError("состояние приложения не инициализировано")
    return state
