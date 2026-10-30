"""Веб-приложение: «вставил адрес — получил отчёт».

Это продуктовая обёртка над движком: тот же Playwright, те же проверки, но
с человеческим языком, историей прогонов и алертами о том, что сломалось.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import uuid
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlparse

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .. import __version__
from ..models import Severity
from ..report import render_html, render_json, render_junit, render_plain, render_sarif
from ..scoring import plain_impact, score_label, top_actions
from .alerts import notify
from .auth import (
    COOKIE_NAME,
    SAFE_METHODS,
    apply_headers,
    auth_configured,
    check_credentials,
    cookie_kwargs,
    csrf_safe,
    is_authenticated,
    is_public_path,
    login_page,
    session_token,
    unauthorized_response,
)
from .limits import RateLimiter, max_concurrent_scans, rate_limit, rate_window_seconds
from .scheduler import Monitor, ScanOptions, Scheduler, default_scanner
from .storage import Run, Site, Storage

LOGGER = logging.getLogger("webscope.webapp")

TEMPLATES_DIR = Path(__file__).parent / "templates"
_LOCAL_DIR = Path(tempfile.gettempdir()) / "webscope-local"
_LOCAL_DIR.mkdir(parents=True, exist_ok=True)

BLOCKER_RULE = "interaction/button-blocked"

SEVERITY_GROUPS = (
    (Severity.CRITICAL, "Критично — сайт работает неправильно", "critical"),
    (Severity.SERIOUS, "Существенно — часть клиентов теряется", "serious"),
    (Severity.MODERATE, "Желательно — стоит поправить", "moderate"),
    (Severity.MINOR, "Мелочи — на ваше усмотрение", "minor"),
)

# Третья категория находок: ошибки на чужих доменах (счётчики, карты, реклама).
# Показываем их отдельной группой, чтобы в таблице были видны все находки,
# но не путались с дефектами сайта.
EXTERNAL_TITLE = "Замечания сканирования — не дефекты сайта (чужие виджеты)"

SEVERITY_LABELS = {
    "critical": "критично",
    "serious": "существенно",
    "moderate": "желательно",
    "minor": "мелочь",
    "external": "виджет",
}

_SCHEDULE_LABELS = {
    "off": "без автоматических проверок",
    "daily": "каждый день",
    "weekly": "каждую неделю",
    "monthly": "каждый месяц",
}


def normalize_url(url: str) -> str:
    """Приводит введённый адрес к полному URL."""
    cleaned = url.strip()
    if not cleaned:
        raise ValueError("Укажите адрес сайта")
    if not cleaned.startswith(("http://", "https://")):
        cleaned = f"https://{cleaned}"
    host = cleaned.split("//", 1)[1].split("/")[0].split(":")[0]
    if "." not in host and host not in ("localhost",):
        raise ValueError("Похоже, это не адрес сайта")
    return cleaned


def _problem_view(group: dict) -> dict:
    """Одна проблема для шаблона: что, где и как проверить."""
    rep = group.get("representative")
    details = getattr(rep, "details", None) or {}
    source = details.get("location") or details.get("location_url") or details.get("resource") or ""
    if not source:
        checker = getattr(rep, "source", "") or ""
        # внутренние пометки вида «webscope.forms» пользователю не интересны
        source = "" if checker.startswith("webscope") else checker
    severity = getattr(rep, "severity", None)
    return {
        "severity": getattr(severity, "value", str(severity or "")),
        "severity_label": SEVERITY_LABELS.get(getattr(severity, "value", ""), getattr(severity, "value", "")),
        "meaning": group["meaning"],
        "fix": group["fix"],
        "url": ", ".join(group["examples"]) if group["examples"] else "",
        "pages_count": group["pages_count"],
        "count": group["count"],
        "rule": group["rule"],
        "selector": getattr(rep, "selector", None) or "",
        "snippet": getattr(rep, "snippet", None) or "",
        "message": getattr(rep, "message", None) or "",
        "source": source,
        "help_url": getattr(rep, "help_url", None) or "",
    }


def build_report_view(storage: Storage, run: Run) -> dict:
    """Готовит данные для страницы отчёта: группы, план действий, дифф."""
    findings = storage.findings_as_models(run.id)
    from ..pages import page_notes
    from ..scoring import group_by_rule, is_site_defect

    blocker_groups = group_by_rule([f for f in findings if f.rule == BLOCKER_RULE])
    blockers = [_problem_view(group) for group in blocker_groups]

    # Находки делятся на три категории, и все три обязаны быть в отчёте:
    # 1) проблемы самого сайта (блокеры кликов входят сюда же — отдельной карточкой),
    # 2) мелочи сайта,
    # 3) замечания сканирования — ошибки на чужих доменах, которые не дефект сайта.
    own = [finding for finding in findings if is_site_defect(finding)]
    external = [finding for finding in findings if not is_site_defect(finding)]
    groups = []
    for severity, title, key in SEVERITY_GROUPS:
        items = group_by_rule(
            [finding for finding in own if finding.severity == severity and finding.rule != BLOCKER_RULE]
        )
        if not items:
            continue
        groups.append(
            {
                "title": title,
                "key": key,
                "count": len(items),
                "problems": [_problem_view(group) for group in items],
            }
        )
    external_items = group_by_rule(external)
    if external_items:
        groups.append(
            {
                "title": EXTERNAL_TITLE,
                "key": "external",
                "count": len(external_items),
                "problems": [_problem_view(group) for group in external_items],
            }
        )

    actions = [
        {
            "meaning": plain_impact(finding)[0],
            "fix": plain_impact(finding)[1],
            "url": finding.url,
            "selector": finding.selector or "",
        }
        for finding in top_actions(findings, limit=3)
    ]

    diff = storage.diff_with_previous(run)
    diff_view = None
    if diff is not None:
        diff_view = {
            "delta": diff.score_after - diff.score_before,
            "score_before": diff.score_before,
            "score_after": diff.score_after,
            "new": [
                {"title": entry.title, "url": entry.url, "severity": entry.severity_after}
                for entry in diff.new_findings[:10]
            ],
            "fixed": [{"title": entry.title, "url": entry.url} for entry in diff.fixed_findings[:10]],
            "new_count": len(diff.new_findings),
            "fixed_count": len(diff.fixed_findings),
        }

    score = run.score if run.score is not None else 100
    return {
        "run": run,
        "score": score,
        "score_label": score_label(score),
        "blockers": blockers,
        "groups": groups,
        "actions": actions,
        "diff": diff_view,
        "total": len(own),
        "external_total": len(external),
        "has_external": bool(external),
        "notes": page_notes(run.raw.get("url"), run.raw.get("final_url")),
    }


def _auth_fields(
    *,
    enabled: str,
    kind: str,
    login: str,
    password: str,
    login_url: str,
    previous_password: str | None = None,
) -> dict:
    """Сводит поля формы «нужна авторизация» к колонкам базы.

    Выключенная галочка или пустой логин чистят вход. Пустой пароль при
    сохранении означает «не менять» — в форме он никогда не предзаполнен.
    """
    login = login.strip()
    if not enabled or not login:
        return {"auth_kind": None, "auth_login": None, "auth_password": None, "auth_login_url": None}
    if kind not in ("basic", "form"):
        kind = "basic"
    login_url = login_url.strip()
    if login_url and not login_url.startswith(("http://", "https://")):
        login_url = f"https://{login_url}"  # пользователь часто пишет домен без схемы
    return {
        "auth_kind": kind,
        "auth_login": login,
        "auth_password": password or (previous_password or ""),
        "auth_login_url": (login_url or None) if kind == "form" else None,
    }


def create_app(
    *,
    db_path: Path | str = "webscope.db",
    options: ScanOptions | None = None,
    check_interval: int = 300,
    allow_private: bool = False,
    scanner_func=None,
    notifier=None,
) -> FastAPI:
    """Собирает приложение: хранилище, монитор, планировщик и маршруты."""
    scan_options = options or ScanOptions()
    if allow_private or os.environ.get("WEBSCOPE_ALLOW_PRIVATE") == "1":
        scan_options.allow_private = True

    storage = Storage(db_path)

    base_scanner = scanner_func or default_scanner

    def scanner_with_local(url: str, options: ScanOptions):
        """Проверка залитых через веб локальных файлов.

        Загруженные файлы раздаются самим приложением по /__local/ — сканировать
        свой же сервер по loopback можно, чужие loopback-адреса остаются под SSRF-защитой.
        """
        parsed = urlparse(url)
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
    tasks: set[asyncio.Task] = set()
    limiter = RateLimiter(rate_limit(), rate_window_seconds())

    def client_key(request: Request) -> str:
        """Ключ лимита: адрес клиента (за прокси нужен доверенный X-Forwarded-For)."""
        return request.client.host if request.client else "unknown"

    def scan_limit_response(request: Request) -> PlainTextResponse | JSONResponse | None:
        """Проверяет лимиты запуска сканов; None — можно запускать."""
        if not limiter.allow(client_key(request)):
            message = "Слишком много запусков проверки с одного адреса. Попробуйте через минуту."
        elif storage.count_running() >= max_concurrent_scans():
            message = "Сейчас выполняется максимум проверок. Попробуйте через пару минут."
        else:
            return None
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": message}, status_code=429)
        return PlainTextResponse(message, status_code=429)


    def trigger(site: Site, background_tasks: BackgroundTasks | None = None) -> Run:
        """Открывает прогон и запускает проверку в фоне.

        Строка прогона создаётся сразу — страница сразу показывает «идёт проверка»,
        а сама проверка уходит в фон (Starlette выполняет синхронные фоновые
        задачи в пуле потоков, поэтому синхронный Playwright не мешает event loop).
        """
        run = monitor.begin(site)
        if background_tasks is not None:
            background_tasks.add_task(monitor.execute, site, run)
        else:
            task = asyncio.create_task(asyncio.to_thread(monitor.execute, site, run))
            tasks.add(task)
            task.add_done_callback(tasks.discard)
        return run

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        scheduler.start()
        yield
        await scheduler.stop()
        storage.close()

    app = FastAPI(title="webscope", version=__version__, lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.storage = storage
    app.state.monitor = monitor
    app.state.scheduler = scheduler
    app.state.limiter = limiter

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

    # --- вход в интерфейс ---
    @app.get("/auth/login", response_class=HTMLResponse)
    def auth_login_form(request: Request, next: str = "/"):
        if not auth_configured():
            return RedirectResponse(url="/", status_code=303)
        return login_page(request, templates)

    @app.post("/auth/login")
    def auth_login(
        request: Request,
        username: str = Form(""),
        password: str = Form(""),
        next: str = Form("/"),
    ):
        if not auth_configured():
            return RedirectResponse(url="/", status_code=303)
        if check_credentials(username, password):
            target = next if next.startswith("/") and not next.startswith("//") else "/"
            response = RedirectResponse(url=target, status_code=303)
            response.set_cookie(value=session_token(), **cookie_kwargs(request))
            return response
        return login_page(request, templates, error="Неверные логин или пароль")

    @app.get("/auth/logout")
    def auth_logout():
        response = RedirectResponse(url="/", status_code=303)
        response.delete_cookie(key=COOKIE_NAME)
        return response

    # --- страницы ---

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
        trigger(site, background_tasks)
        return RedirectResponse(url=f"/sites/{site.id}", status_code=303)

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
        runs = [run for run in storage.list_runs(site.id, limit=60) if run.status == "ok"]
        counts = storage.severity_counts([run.id for run in runs])
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
        job_id = uuid.uuid4().hex
        base = _LOCAL_DIR / job_id
        base.mkdir(parents=True, exist_ok=True)
        for f, p in zip(files, paths):
            rel = Path(p)
            # защита от выхода за пределы
            safe = Path(*[part for part in rel.parts if part not in ("..", ".", "")])
            if not safe.parts:
                safe = Path(f.filename or "index.html")
            dest = base / safe
            dest.parent.mkdir(parents=True, exist_ok=True)
            content = await f.read()
            dest.write_bytes(content)
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

    @app.get("/api/sites/{site_id}/report.txt", response_class=PlainTextResponse)
    def api_report_text(site_id: int):
        site = storage.get_site(site_id)
        if site is None:
            raise HTTPException(status_code=404, detail="Сайт не найден")
        last = storage.latest_ok_run(site.id)
        if last is None:
            raise HTTPException(status_code=404, detail="Отчёт ещё не готов")
        return render_plain(_result_from_run(storage, last))

    @app.get("/api/sites/{site_id}/report.json")
    def api_report_json(site_id: int):
        site = storage.get_site(site_id)
        if site is None:
            raise HTTPException(status_code=404, detail="Сайт не найден")
        last = storage.latest_ok_run(site.id)
        if last is None:
            raise HTTPException(status_code=404, detail="Отчёт ещё не готов")
        return JSONResponse(render_json(_result_from_run(storage, last)))

    @app.get("/api/sites/{site_id}/report.html", response_class=HTMLResponse)
    def api_report_html(site_id: int):
        site = storage.get_site(site_id)
        if site is None:
            raise HTTPException(status_code=404, detail="Сайт не найден")
        last = storage.latest_ok_run(site.id)
        if last is None:
            raise HTTPException(status_code=404, detail="Отчёт ещё не готов")
        return render_html(_result_from_run(storage, last))

    @app.get("/api/sites/{site_id}/report.sarif")
    def api_report_sarif(site_id: int):
        site = storage.get_site(site_id)
        if site is None:
            raise HTTPException(status_code=404, detail="Сайт не найден")
        last = storage.latest_ok_run(site.id)
        if last is None:
            raise HTTPException(status_code=404, detail="Отчёт ещё не готов")
        return JSONResponse(json.loads(render_sarif(_result_from_run(storage, last))))

    @app.get("/api/sites/{site_id}/report.xml")
    def api_report_junit(site_id: int):
        site = storage.get_site(site_id)
        if site is None:
            raise HTTPException(status_code=404, detail="Сайт не найден")
        last = storage.latest_ok_run(site.id)
        if last is None:
            raise HTTPException(status_code=404, detail="Отчёт ещё не готов")
        from fastapi.responses import PlainTextResponse

        return PlainTextResponse(render_junit(_result_from_run(storage, last)), media_type="application/xml")

    try:
        app.mount("/__local", StaticFiles(directory=str(_LOCAL_DIR), html=True), name="local_static")
    except (OSError, RuntimeError) as exc:  # каталог раздачи не создался — локальная загрузка будет недоступна
        LOGGER.warning("не удалось смонтировать /__local: %s", exc)

    return app


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
