"""Веб-приложение: «вставил адрес — получил отчёт».

Здесь только сборка: хранилище, монитор, планировщик, шаблоны и роутеры.
Обработчики живут в `webapp/routes/`, состояние — в `webapp/state.py`.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .. import __version__
from . import middleware
from .alerts import notify
from .auth import auth_configured, is_authenticated
from .limits import RateLimiter, rate_limit, rate_window_seconds
from .mock_scanner import mock_scanner
from .presentation import register_filters
from .routes import api, auth, dashboard, pages, reports
from .routes import uploads as upload_routes
from .scheduler import Monitor, Scheduler, default_scanner
from .services.site_service import ensure_default_organization, migrate_add_organization_id
from .state import STATE_KEY, AppState
from .storage import Storage
from .uploads import LOCAL_DIR, SandboxedLocalFiles
from .webhook_queue import create_webhook_queue

LOGGER = logging.getLogger(__name__)
TEMPLATES_DIR = Path(__file__).parent / "templates"


def create_app(
    *,
    db_path: Path | str | None = None,
    options=None,
    check_interval: int = 300,
    allow_private: bool = False,
    scanner_func=None,
    notifier=None,
    local_dir: Path | str | None = None,
) -> FastAPI:
    """Собирает приложение из независимых частей."""
    from .scheduler import ScanOptions

    if db_path is None:
        db_path = os.environ.get("WEBSCOPE_DB_PATH", "data/webscope.db")
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    scan_options = options or ScanOptions()
    if allow_private:
        scan_options.allow_private = True
    elif os.environ.get("WEBSCOPE_ALLOW_PRIVATE") == "1":
        # S11: env больше не отключает SSRF-защиту глобально — только предупреждает.
        # Явный allow_private=True по-прежнему работает (для /__local/ и тестов).
        logging.getLogger(__name__).warning(
            "WEBSCOPE_ALLOW_PRIVATE=1 is deprecated and ignored. Use allow_private=True per-scan instead."
        )

    storage = Storage(db_path)
    migrate_add_organization_id(storage)
    ensure_default_organization(storage)

    upload_dir = Path(local_dir) if local_dir is not None else LOCAL_DIR
    upload_dir.mkdir(parents=True, exist_ok=True)

    base_scanner = mock_scanner if os.environ.get("WEBSCOPE_MOCK_SCANNER") == "1" else (scanner_func or default_scanner)

    def scanner_with_local(url: str, options: ScanOptions):
        """Свои загруженные файлы раздаются по /__local/ и требуют loopback."""
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
    templates.env.globals["is_authenticated"] = is_authenticated
    templates.env.globals["mock_scanner_enabled"] = os.environ.get("WEBSCOPE_MOCK_SCANNER") == "1"
    register_filters(templates.env)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        scheduler.start()
        webhook_queue = await create_webhook_queue(storage)
        state.webhook_queue = webhook_queue
        try:
            yield
        finally:
            await webhook_queue.stop()
            await scheduler.stop()
            storage.close()

    app = FastAPI(
        title="webscope",
        version=__version__,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
    )
    state = AppState(
        storage=storage,
        monitor=monitor,
        scheduler=scheduler,
        templates=templates,
        limiter=RateLimiter(rate_limit(), rate_window_seconds()),
        scan_options=scan_options,
        local_dir=upload_dir,
    )
    setattr(app.state, STATE_KEY, state)

    # Публичный healthcheck регистрируем до middleware и роутеров.
    app.add_api_route("/healthz", lambda: {"status": "ok"}, methods=["GET"])

    middleware.install(app)

    app.include_router(auth.router)
    app.include_router(pages.router)
    app.include_router(dashboard.router)
    app.include_router(api.router)
    app.include_router(reports.router)
    app.include_router(upload_routes.router)

    static_dir = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    try:
        app.mount("/__local", SandboxedLocalFiles(directory=str(upload_dir), html=True), name="local_static")
    except (OSError, RuntimeError) as exc:
        LOGGER.warning("не удалось смонтировать /__local: %s", exc)

    return app


__all__ = ["create_app"]
