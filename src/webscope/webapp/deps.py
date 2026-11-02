"""Общие действия маршрутов: лимиты запуска, создание прогона, поиск сайта.

Здесь нет ни одного `@router.get`: только операции над состоянием, чтобы
одинаковое поведение у страниц и JSON API не расходилось.
"""

from __future__ import annotations

import asyncio

from fastapi import BackgroundTasks, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from .limits import max_concurrent_scans
from .scheduler import Site
from .state import AppState
from .storage import Run


def client_key(request: Request) -> str:
    """Ключ лимита: адрес клиента (за прокси нужен доверенный X-Forwarded-For)."""
    return request.client.host if request.client else "unknown"


def scan_limit_response(state: AppState, request: Request) -> PlainTextResponse | JSONResponse | None:
    """Проверяет лимиты запуска сканов; None — можно запускать."""
    if not state.limiter.allow(client_key(request)):
        message = "Слишком много запусков проверки с одного адреса. Попробуйте через минуту."
    elif state.storage.count_running() >= max_concurrent_scans():
        message = "Сейчас выполняется максимум проверок. Попробуйте через пару минут."
    else:
        return None
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": message}, status_code=429)
    return PlainTextResponse(message, status_code=429)


def trigger(state: AppState, site: Site, background_tasks: BackgroundTasks | None = None) -> Run:
    """Открывает прогон и запускает проверку в фоне.

    Строка прогона создаётся сразу — страница сразу показывает «идёт проверка»,
    а сама проверка уходит в фон (Starlette выполняет синхронные фоновые
    задачи в пуле потоков, поэтому синхронный Playwright не мешает event loop).
    """
    run = state.monitor.begin(site)
    if background_tasks is not None:
        background_tasks.add_task(state.monitor.execute, site, run)
    else:
        task = asyncio.create_task(asyncio.to_thread(state.monitor.execute, site, run))
        state.tasks.add(task)
        task.add_done_callback(state.tasks.discard)
    return run


def get_site_or_404(state: AppState, site_id: int) -> Site:
    site = state.storage.get_site(site_id)
    if site is None:
        raise HTTPException(status_code=404, detail="Сайт не найден")
    return site


def index_cards(state: AppState) -> list[dict]:
    """Сайты с последним прогоном — данные главной страницы (нужны и в ошибках)."""
    return [{"site": item, "run": state.storage.latest_run(item.id)} for item in state.storage.list_sites()]
