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
from .limits import RateLimiter, max_concurrent_scans, rate_limit, rate_window_seconds
from .routes import api, auth, pages, reports
from .routes import uploads as upload_routes
from .scheduler import Monitor, ScanOptions, Scheduler, default_scanner
from .state import STATE_KEY, AppState
from .storage import Storage
from .uploads import LOCAL_DIR, SandboxedLocalFiles

LOGGER = logging.getLogger("webscope.webapp")

TEMPLATES_DIR = Path(__file__).parent / "templates"


def create_app(
    *,
    db_path: Path | str = "webscope.db",
    options: ScanOptions | None = None,
    check_interval: int = 300,
    allow_private: bool = False,
    scanner_func=None,
    notifier=None,
    local_dir: Path | str | None = None,
) -> FastAPI:
    """Собирает приложение: хранилище, монитор, планировщик и маршруты."""
    scan_options = options or ScanOptions()
    if allow_private or os.environ.get("WEBSCOPE_ALLOW_PRIVATE") == "1":
        scan_options.allow_private = True

    storage = Storage(db_path)
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
        # прогоны, оборванные падением прошлого процесса, иначе навсегда
        # остаются 'running': главная показывает «выполывается», а лимит
        # одновременных проверок съеден навсегда
        strays = storage.reconcile_running()
        if strays:
            LOGGER.warning("закрыто прерванных прогонов: %d", strays)
        scheduler.start()
        yield
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

    # P0 разделение: подключение роутеров
    app.include_router(auth_routes.router)
    app.include_router(pages_routes.router)
    app.include_router(upload_routes.router)

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
    app.include_router(api.router)
    app.include_router(reports.router)
    app.include_router(upload_routes.router)

    def index_cards() -> list[dict]:
        """Сайты с последним прогоном — данные главной страницы (нужны и в ошибках)."""
        return [{"site": item, "run": storage.latest_run(item.id)} for item in storage.list_sites()]

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "sites": index_cards(),
                "schedules": _SCHEDULE_LABELS,
                "error": None,
            },
        )

    @app.get("/sites", response_class=HTMLResponse)
    def list_sites(request: Request):
        # P0: для защиты — если auth включён, проверяем cookie
        if auth_configured() and not is_authenticated(request):
            return apply_headers(unauthorized_response(request))
        return templates.TemplateResponse(request, "sites.html", {"sites": storage.list_sites()})

    @app.post("/sites")
    def create_site(
        request: Request,
        background_tasks: BackgroundTasks,
        url: str = Form(...),
        email: str = Form(""),
        telegram_chat: str = Form(""),
        schedule: str = Form("off"),
        auth_enabled: str = Form(""),
        auth_kind: str = Form("basic"),
        auth_login: str = Form(""),
        auth_password: str = Form(""),
        auth_login_url: str = Form(""),
    ):
        limited = scan_limit_response(request)
        if limited is not None:
            return limited

        try:
            normalized = normalize_url(url)
        except ValueError as exc:
            return templates.TemplateResponse(
                request,
                "index.html",
                {
                    "sites": index_cards(),
                    "schedules": _SCHEDULE_LABELS,
                    "error": str(exc),
                },
                status_code=400,
            )

        if auth_enabled and not auth_login.strip():
            return templates.TemplateResponse(
                request,
                "index.html",
                {
                    "sites": index_cards(),
                    "schedules": _SCHEDULE_LABELS,
                    "error": "Включена авторизация, но не указан логин.",
                },
                status_code=400,
            )

        auth = _auth_fields(
            enabled=auth_enabled,
            kind=auth_kind,
            login=auth_login,
            password=auth_password,
            login_url=auth_login_url,
        )
        site = storage.add_site(
            normalized,
            email=email.strip() or None,
            telegram_chat=telegram_chat.strip() or None,
            schedule=schedule if schedule in _SCHEDULE_LABELS else "off",
            **auth,
        )
        if auth["auth_kind"] is not None:
            # URL мог быть уже известен, а add_site существующую строку не трогает:
            # форма с галочкой — источник актуальных кредов, дописываем их.
            # Галочка выключена — вход не трогаем, чтобы перепроверка без неё
            # не чистила настроенные ранее креды.
            storage.update_site(site.id, **auth)
            # add_site вернул объект до записи кредов — trigger() из него
            # увидел бы site без входа, и первый прогон шёл бы без авторизации.
            site = storage.get_site(site.id) or site
        trigger(site, background_tasks)
        return RedirectResponse(url=f"/sites/{site.id}", status_code=303)

    @app.get("/sites")
    def sites_index():
        """Список сайтов живёт на главной; /sites — адрес после входа."""
        return RedirectResponse(url="/", status_code=303)

    @app.get("/sites/{site_id}", response_class=HTMLResponse)
    def site_page(request: Request, site_id: int):
        site = storage.get_site(site_id)
        if site is None:
            raise HTTPException(status_code=404, detail="Сайт не найден")

        pending = storage.running_run(site.id)
        last = storage.latest_ok_run(site.id)
        newest = storage.latest_run(site.id)
        last_error = newest.error if newest and newest.status == "error" else None
        view = build_report_view(storage, last) if last else None
        return templates.TemplateResponse(
            request,
            "site.html",
            {
                "site": site,
                "view": view,
                "pending": pending,
                "last_error": last_error,
                "schedule_label": _SCHEDULE_LABELS.get(site.schedule, site.schedule),
                "download_formats": DOWNLOAD_FORMATS,
                "download_sample": download_filename(site, last, "json") if last else None,
                "download_default_name": default_report_stem(site, last) if last else None,
                "download_date": human_date(last.started_at) if last else None,
            },
        )

    @app.post("/sites/{site_id}/scan")
    def rescan(request: Request, site_id: int, background_tasks: BackgroundTasks):
        limited = scan_limit_response(request)
        if limited is not None:
            return limited
        site = storage.get_site(site_id)
        if site is None:
            raise HTTPException(status_code=404, detail="Сайт не найден")
        trigger(site, background_tasks)
        return RedirectResponse(url=f"/sites/{site.id}", status_code=303)

    @app.get("/sites/{site_id}/history", response_class=HTMLResponse)
    def site_history(request: Request, site_id: int):
        site = storage.get_site(site_id)
        if site is None:
            raise HTTPException(status_code=404, detail="Сайт не найден")
        runs = storage.list_runs(site.id, limit=60)
        ok_runs = [run for run in runs if run.status == "ok"]
        counts = storage.severity_counts([run.id for run in ok_runs])
        return templates.TemplateResponse(
            request,
            "history.html",
            {
                "site": site,
                "runs": runs,
                "counts": counts,
            },
        )

    @app.get("/sites/{site_id}/settings", response_class=HTMLResponse)
    def site_settings(request: Request, site_id: int, saved: bool = False):
        site = storage.get_site(site_id)
        if site is None:
            raise HTTPException(status_code=404, detail="Сайт не найден")
        return templates.TemplateResponse(
            request,
            "settings.html",
            {
                "site": site,
                "schedules": _SCHEDULE_LABELS,
                "saved": saved,
            },
        )

    @app.post("/sites/{site_id}/settings")
    def site_settings_save(
        site_id: int,
        email: str = Form(""),
        telegram_chat: str = Form(""),
        schedule: str = Form("off"),
        auth_enabled: str = Form(""),
        auth_kind: str = Form("basic"),
        auth_login: str = Form(""),
        auth_password: str = Form(""),
        auth_login_url: str = Form(""),
    ):
        site = storage.get_site(site_id)
        if site is None:
            raise HTTPException(status_code=404, detail="Сайт не найден")
        schedule = schedule if schedule in _SCHEDULE_LABELS else "off"
        storage.update_site(
            site.id,
            email=email.strip() or None,
            telegram_chat=telegram_chat.strip() or None,
            schedule=schedule,
            **_auth_fields(
                enabled=auth_enabled,
                kind=auth_kind,
                login=auth_login,
                password=auth_password,
                login_url=auth_login_url,
                previous_password=site.auth_password,
            ),
        )
        # расписание могло измениться — пересчитываем дату следующего запуска
        # по свежей строке из БД, а не по устаревшему объекту
        updated = storage.get_site(site.id)
        if updated is not None:
            monitor.schedule_next(updated)
        return RedirectResponse(url=f"/sites/{site.id}/settings?saved=1", status_code=303)

    @app.post("/sites/{site_id}/delete")
    def site_delete(site_id: int):
        if not storage.delete_site(site_id):
            raise HTTPException(status_code=404, detail="Сайт не найден")
        return RedirectResponse(url="/", status_code=303)

    # --- API ---

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    @app.get("/api/sites")
    def api_sites():
        sites = storage.list_sites()
        payload = []
        for site in sites:
            last = storage.latest_ok_run(site.id)
            payload.append(
                {
                    **site.to_dict(),
                    "last_run": last.to_dict() if last else None,
                    "score": last.score if last else None,
                }
            )
        return {"sites": payload}

    @app.get("/api/sites/{site_id}")
    def api_site(site_id: int):
        site = storage.get_site(site_id)
        if site is None:
            raise HTTPException(status_code=404, detail="Сайт не найден")
        last = storage.latest_ok_run(site.id)
        newest = storage.latest_run(site.id)
        findings = storage.findings_of(last.id) if last else []
        diff = storage.diff_with_previous(last) if last else None
        return {
            "site": site.to_dict(),
            "last_run": last.to_dict() if last else None,
            "last_error": newest.error if newest and newest.status == "error" else None,
            "findings": [finding.to_dict() for finding in findings],
            "diff": diff.to_dict() if diff else None,
        }

    @app.get("/api/sites/{site_id}/runs")
    def api_runs(site_id: int):
        site = storage.get_site(site_id)
        if site is None:
            raise HTTPException(status_code=404, detail="Сайт не найден")
        return {"runs": [run.to_dict() for run in storage.list_runs(site.id, limit=100)]}

    @app.post("/api/sites/{site_id}/scan")
    def api_scan(request: Request, site_id: int, background_tasks: BackgroundTasks):
        limited = scan_limit_response(request)
        if limited is not None:
            return limited
        site = storage.get_site(site_id)
        if site is None:
            raise HTTPException(status_code=404, detail="Сайт не найден")
        run = trigger(site, background_tasks)
        return JSONResponse({"status": "started", "site_id": site_id, "run_id": run.id}, status_code=202)

    @app.post("/upload")
    async def upload_files(
        request: Request,
        files: list[UploadFile] = File(...),
        paths: list[str] = Form(...),
        background_tasks: BackgroundTasks = None,
    ):
        limited = scan_limit_response(request)
        if limited is not None:
            return limited
        if not files:
            raise HTTPException(status_code=400, detail="Нет файлов")
        if len(files) > MAX_UPLOAD_FILES:
            raise HTTPException(status_code=413, detail=f"Слишком много файлов (максимум {MAX_UPLOAD_FILES})")
        if len(paths) != len(files):
            raise HTTPException(status_code=400, detail="Число путей не совпадает с числом файлов")

        job_id = uuid.uuid4().hex
        base = _LOCAL_DIR / job_id
        base.mkdir(parents=True, exist_ok=True)
        total_bytes = 0
        try:
            for f, raw_path in zip(files, paths):
                # Абсолютный путь или выход за пределы каталога загрузки —
                # отказ. Раньше фильтр выбрасывал только «..», а «/etc/passwd»
                # оставался абсолютным и записывался мимо каталога задания.
                relative = Path((raw_path or "").replace("\\", "/"))
                if relative.is_absolute():
                    raise HTTPException(status_code=400, detail="Абсолютный путь файла не допускается")
                safe = Path(*[part for part in relative.parts if part not in ("..", ".", "")])
                if not safe.parts:
                    safe = Path(Path(f.filename or "index.html").name)
                dest = (base / safe).resolve()
                if not dest.is_relative_to(base.resolve()):
                    raise HTTPException(status_code=400, detail="Недопустимый путь файла")
                content = await f.read(MAX_UPLOAD_FILE_BYTES + 1)
                total_bytes += len(content)
                if len(content) > MAX_UPLOAD_FILE_BYTES or total_bytes > MAX_UPLOAD_TOTAL_BYTES:
                    raise HTTPException(status_code=413, detail="Загруженные файлы слишком большие")
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(content)
        except HTTPException:
            shutil.rmtree(base, ignore_errors=True)
            raise

        _prune_local_uploads(keep=MAX_UPLOAD_JOBS)
        # выбираем стартовый файл
        index = base / "index.html"
        if not index.exists():
            candidates = list(base.rglob("index.html"))
            if candidates:
                index = candidates[0]
            else:
                htmls = list(base.rglob("*.html"))
                index = htmls[0] if htmls else (base / "index.html")
        rel_idx = index.relative_to(base)
        # Адрес берём из реального запроса (host:port), а не из env — файлы
        # раздаёт это же приложение, и сканер должен ходить туда же.
        origin = str(request.base_url).rstrip("/")
        url = f"{origin}/__local/{job_id}/{rel_idx.as_posix()}"
        try:
            normalized = normalize_url(url)
        except ValueError:
            normalized = url
        site = storage.add_site(normalized, email=None, telegram_chat=None, schedule="off")
        trigger(site, background_tasks)
        return {"url": normalized, "site_id": site.id}

    def report_payload(site_id: int, fmt: str) -> tuple[Site, Run, str]:
        """Готовый отчёт: сайт, прогон и содержимое в нужном формате."""
        site = storage.get_site(site_id)
        if site is None:
            raise HTTPException(status_code=404, detail="Сайт не найден")
        last = storage.latest_ok_run(site.id)
        if last is None:
            raise HTTPException(status_code=404, detail="Отчёт ещё не готов")
        return site, last, REPORT_RENDERERS[fmt](_result_from_run(storage, last))

    def report_response(site_id: int, fmt: str, download: bool, filename: str | None = None) -> Response:
        """Отчёт для просмотра в браузере или файлом на скачивание.

        ``filename`` — имя, выбранное пользователем в панели сохранения;
        оно чистится (``safe_report_stem``) и попадает в ``Content-Disposition``.
        Заголовок важнее атрибута ``download`` в ссылке, поэтому имя задаётся
        именно здесь, а не в разметке.
        """
        site, run, payload = report_payload(site_id, fmt)
        headers: dict[str, str] = {}
        if download:
            headers["Content-Disposition"] = content_disposition(
                download_filename(site, run, fmt, filename),
                fallback=download_filename(site, run, fmt),
            )
            headers["Cache-Control"] = "no-store"
        return Response(content=payload, media_type=REPORT_MEDIA_TYPES[fmt], headers=headers)

    @app.get("/api/sites/{site_id}/report.txt")
    def api_report_text(site_id: int, download: bool = False, filename: str | None = None):
        return report_response(site_id, "txt", download, filename)

    @app.get("/api/sites/{site_id}/report.json")
    def api_report_json(site_id: int, download: bool = False, filename: str | None = None):
        return report_response(site_id, "json", download, filename)

    @app.get("/api/sites/{site_id}/report.html")
    def api_report_html(site_id: int, download: bool = False, filename: str | None = None):
        return report_response(site_id, "html", download, filename)

    @app.get("/api/sites/{site_id}/report.sarif")
    def api_report_sarif(site_id: int, download: bool = False, filename: str | None = None):
        return report_response(site_id, "sarif", download, filename)

    @app.get("/api/sites/{site_id}/report.xml")
    def api_report_junit(site_id: int, download: bool = False, filename: str | None = None):
        return report_response(site_id, "xml", download, filename)


    try:
        app.mount("/__local", SandboxedLocalFiles(directory=str(upload_dir), html=True), name="local_static")
    except (OSError, RuntimeError) as exc:  # каталог раздачи не создался — локальная загрузка будет недоступна
        LOGGER.warning("не удалось смонтировать /__local: %s", exc)

    return app


__all__ = ["create_app"]

def _result_from_run(storage: Storage, run: Run):
    """Собирает ScanResult из сохранённого прогона."""
    from ..models import ScanResult

    result = ScanResult(
        url=run.raw.get("url", ""),
        final_url=run.raw.get("final_url"),
        title=run.raw.get("title"),
        archetype=run.raw.get("archetype", {}),
        duration_ms=run.duration_ms,
        pages_scanned=run.pages_scanned,
    )
    result.findings = storage.findings_as_models(run.id)
    return result


# Полная реализация — в subagent/security-plan

