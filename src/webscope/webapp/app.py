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
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .. import __version__
from ..models import Finding, ScanResult, Severity
from ..webapp.scheduler import CrawlOutcome
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
from .limits import RateLimiter, rate_limit, rate_window_seconds
from .routes import api, auth, dashboard, pages, reports
from .routes import uploads as upload_routes
from .scheduler import Monitor, ScanOptions, Scheduler, default_scanner
from .services.site_service import ensure_default_organization, migrate_add_organization_id
from .state import STATE_KEY, AppState
from .storage import Storage
from .uploads import LOCAL_DIR, SandboxedLocalFiles
from .webhook_queue import create_webhook_queue

TEMPLATES_DIR = Path(__file__).parent / "templates"


def _mock_scanner(url: str, options: ScanOptions) -> CrawlOutcome:
    """Мок-сканер для тестов: возвращает детерминированный результат мгновенно."""
    from ..models import Finding, ScanResult, Severity
    findings = [
        Finding(
            rule="content/image-alt",
            severity=Severity.SERIOUS,
            title="Изображение без alt",
            message="У <img> нет атрибута alt",
            url=url,
            selector="main > img",
            snippet="<img src='/logo.png'>",
            help_url="https://www.w3.org/WAI/WCAG22/Understanding/non-text-content.html",
            source="webscope.content",
            details={"evidence": "001_content_image_alt.png"},
        ),
        Finding(
            rule="forms/control-without-label",
            severity=Severity.MODERATE,
            title="Поле без подписи",
            message="У поля нет <label>",
            url=url,
            selector="input[name='email']",
            snippet="<input name='email'>",
            help_url="https://www.w3.org/WAI/WCAG22/Understanding/label-in-name.html",
            source="webscope.forms",
            details={},
        ),
    ]
    result = ScanResult(
        url=url,
        final_url=url,
        title="Test Site",
        findings=findings,
        duration_ms=5000,
        pages_scanned=3,
    )
    return CrawlOutcome(result)


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

    # Используем мок-сканер если задан WEBSCOPE_MOCK_SCANNER=1
    if os.environ.get("WEBSCOPE_MOCK_SCANNER") == "1":
        base_scanner = _mock_scanner
    else:
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

    @app.middleware("http")
    async def csp_middleware(request: Request, call_next):
        """Content Security Policy header for security."""
        response = await call_next(request)
        # Skip CSP for sandboxed local files - they set their own CSP
        if request.url.path.startswith("/__local/"):
            return response
        # CSP enforce mode - all inline styles/scripts moved to static files
        csp = (
            "default-src 'self'; "
            "script-src 'self' https://cdn.jsdelivr.net; "
            "style-src 'self'; "
            "img-src 'self' data:; "
            "font-src 'self'; "
            "connect-src 'self'; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self';"
        )
        response.headers["Content-Security-Policy"] = csp
        return response

    # порядок важен: страницы объявляются раньше API, чтобы `/sites` не перехватил
    # ничего лишнего, а `/api/sites/{site_id}` не затенил отчёты
    app.include_router(auth.router)
    app.include_router(pages.router)
    app.include_router(dashboard.router)
    app.include_router(api.router)
    app.include_router(reports.router)
    app.include_router(upload_routes.router)

    # Serve static files (CSS, JS)
    static_dir = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    try:
        app.mount("/__local", SandboxedLocalFiles(directory=str(upload_dir), html=True), name="local_static")
    except (OSError, RuntimeError) as exc:  # каталог раздачи не создался — локальная загрузка будет недоступна
        LOGGER.warning("не удалось смонтировать /__local: %s", exc)

    return app


__all__ = ["create_app"]
