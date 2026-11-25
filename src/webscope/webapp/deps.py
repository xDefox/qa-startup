"""Общие действия маршрутов: лимиты запуска, создание прогона, поиск сайта.

Здесь нет ни одного `@router.get`: только операции над состоянием, чтобы
одинаковое поведение у страниц и JSON API не расходилось.
"""

from __future__ import annotations

import asyncio

from fastapi import BackgroundTasks, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from .auth import public_user
from .limits import client_key, max_concurrent_scans
from .presentation import SiteCard
from .scheduler import Site
from .services.site_service import list_sites as list_sites_service
from .state import AppState
from .storage import Run


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


def get_site_or_404(state: AppState, site_id: int, owner_id: int | None = None) -> Site:
    """Сайт по id. Публичный сервис: сайт открывается всем, owner_id не проверяется."""
    site = state.storage.get_site(site_id)
    if site is None:
        raise HTTPException(status_code=404, detail="Сайт не найден")
    return site


def index_cards(state: AppState, owner_id: int | None = None) -> list[SiteCard]:
    """Сайты с последним прогоном — данные главной и кабинета. Публичная модель — все сайты."""
    return [
        SiteCard(site=item, run=state.storage.latest_run(item.id))
        for item in list_sites_service(state.storage)
    ]


def get_current_user(request: Request) -> dict:
    """Текущий пользователь из сессии.

    Middleware уже отклонил анонимные запросы к закрытым страницам, поэтому
    здесь пользователь обязан быть. Для публичных страниц шаблоны используют
    ``current_user(request)``, который умеет возвращать None.
    """
    user = public_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Требуется вход")
    return user
