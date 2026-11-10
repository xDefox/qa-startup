"""Веб-приложение: «вставил адрес — получил отчёт».

Это продуктовая обёртка над движком: тот же Playwright, те же проверки, но
с человеческим языком, историей прогонов и алертами о том, что сломалось.

Здесь только сборка: хранилище, монитор, планировщик, шаблоны и подключение
роутеров. Сами обработчики — в `webapp/routes/`, состояние — в `webapp/state.py`.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from fastapi.templating import Jinja2Templates

from .. import __version__
from .alerts import notify
from .auth import (
    SAFE_METHODS,
    apply_headers,
    auth_configured,
    csrf_safe,
    is_authenticated,
    is_public_path,
    unauthorized_response,
)
from .webhook_queue import create_webhook_queue
from .limits import RateLimiter, rate_limit, rate_window_seconds
from .routes import api, auth, dashboard, pages, reports
from .routes import uploads as upload_routes
from .scheduler import Monitor, ScanOptions, Scheduler, default_scanner
from .services.site_service import migrate_add_organization_id, ensure_default_organization
from .state import STATE_KEY, AppState
from .storage import Storage
from .uploads import LOCAL_DIR, SandboxedLocalFiles

LOGGER = logging.getLogger("webscope.webapp")

TEMPLATES_DIR = Path(__file__).parent / "templates"


def create_app(
    *,
    db_path: Path | str | None = None,
    options: ScanOptions | None = None,
    check_interval: int = 300,
    allow_private: bool = False,
    scanner_func=None,
    notifier=None,
    local_dir: Path | str | None = None,
) -> FastAPI:
    """Собирает приложение: хранилище, монитор, планировщик и маршруты."""
    if db_path is None:
        db_path = os.environ.get("WEBSCOPE_DB_PATH", "data/webscope.db")
    db_path = Path(db_path)
    # Гарантируем, что директория для БД существует
    db_path.parent.mkdir(parents=True, exist_ok=True)
    
    scan_options = options or ScanOptions()
    if allow_private or os.environ.get("WEBSCOPE_ALLOW_PRIVATE") == "1":
        scan_options.allow_private = True

    storage = Storage(db_path)
    # Миграция мультиарендности: добавляем organization_id колонку к существующим БД
    migrate_add_organization_id(storage)
    # Гарантируем дефолтную организацию (для форм и совместимости)
    ensure_default_organization(storage)
    # каталог загруженных сборок: по умолчанию общий, тесты передают свой
    upload_dir = Path(local_dir) if local_dir is not None else LOCAL_DIR
    upload_dir.mkdir(parents=True, exist_ok=True)

    base_scanner = scanner_func or default_scanner

    def scanner_with_local(url: str, options: ScanOptions):
        """Проверка залитых через веб локальных файлов.

        Загруженные файлы раздаются самим приложением по /__local/ — сканировать
        свой же сервер по loopback можно, чужие loopback-адреса остаются под SSRF-защитой.
        """
        parsed = urlsplit(url)
        if parsed.hostname in ("127.0.0.1", "localhost") and parsed.path.startswith("/__local/"):
            options = replace(options, allow_private=True)
        return base_scanner(url, options)

    monitor = Monitor(
        storage,
        scan_options,
        scanner_func=scanner_with_local,
        notifier=notifier or notify,
    )
    scheduler = Scheduler(monitor, storage, check_interval=check_interval)
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    templates.env.globals["auth_enabled"] = auth_configured()
    limiter = RateLimiter(rate_limit(), rate_window_seconds())

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        scheduler.start()
        # Initialize webhook queue
        webhook_queue = await create_webhook_queue(storage)
        state.webhook_queue = webhook_queue
        yield
        await webhook_queue.stop()
        await scheduler.stop()
        storage.close()

    app = FastAPI(title="webscope", version=__version__, lifespan=lifespan, docs_url=None, redoc_url=None)
    state = AppState(
        storage=storage,
        monitor=monitor,
        scheduler=scheduler,
        templates=templates,
        limiter=limiter,
        scan_options=scan_options,
        local_dir=upload_dir,
    )
    setattr(app.state, STATE_KEY, state)

    # /healthz — public service endpoint, must be registered before middleware/routers
    # so it's always accessible for CI and monitoring regardless of auth config
    app.add_api_route("/healthz", lambda: {"status": "ok"}, methods=["GET"])

    @app.middleware("http")
    async def guard(request: Request, call_next):
        """Вход и CSRF для всех маршрутов, кроме публичных.

        Пока ``WEBSCOPE_AUTH_PASSWORD`` не задан, приложение работает как демо
        (и `webscope serve` об этом предупреждает). Как только пароль задан,
        без cookie не открывается ничего: ни страницы, ни API, ни отчёты.
        """
        if auth_configured() and not is_public_path(request.url.path):
            if request.method not in SAFE_METHODS and not csrf_safe(request):
                return PlainTextResponse("Запрос с чужого Origin отклонён", status_code=403)
            if not is_authenticated(request):
                return apply_headers(unauthorized_response(request))
        response = await call_next(request)
        return apply_headers(response)

    # порядок важен: страницы объявляются раньше API, чтобы `/sites` не перехватил
    # ничего лишнего, а `/api/sites/{site_id}` не затенил отчёты
    app.include_router(auth.router)
    app.include_router(pages.router)
    app.include_router(dashboard.router)
    app.include_router(api.router)
    app.include_router(reports.router)
    app.include_router(upload_routes.router)

    try:
        app.mount("/__local", SandboxedLocalFiles(directory=str(upload_dir), html=True), name="local_static")
    except (OSError, RuntimeError) as exc:  # каталог раздачи не создался — локальная загрузка будет недоступна
        LOGGER.warning("не удалось смонтировать /__local: %s", exc)

    return app


__all__ = ["create_app"]
