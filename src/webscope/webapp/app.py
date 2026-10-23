"""Веб-приложение: «вставил адрес — получил отчёт».

Это продуктовая обёртка над движком: тот же Playwright, те же проверки, но
с человеческим языком, историей прогонов и алертами о том, что сломалось.
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ..models import Severity
from ..report import render_plain
from ..scoring import plain_impact, score_label, top_actions
from .alerts import notify
from .scheduler import Monitor, ScanOptions, Scheduler, default_scanner
from .storage import Run, Site, Storage

LOGGER = logging.getLogger("webscope.webapp")

TEMPLATES_DIR = Path(__file__).parent / "templates"

BLOCKER_RULE = "interaction/button-blocked"

SEVERITY_GROUPS = (
    (Severity.CRITICAL, "Критично — сайт работает неправильно", "critical"),
    (Severity.SERIOUS, "Существенно — часть клиентов теряется", "serious"),
    (Severity.MODERATE, "Желательно — стоит поправить", "moderate"),
    (Severity.MINOR, "Мелочи — на ваше усмотрение", "minor"),
)

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
    if "." not in cleaned.split("//", 1)[1].split("/")[0]:
        raise ValueError("Похоже, это не адрес сайта")
    return cleaned


def _problem_view(group: dict) -> dict:
    """Одна проблема для шаблона: что, где и как проверить."""
    rep = group.get("representative")
    details = getattr(rep, "details", None) or {}
    source = details.get("location") or details.get("location_url") or details.get("resource") or ""
    return {
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
    }


def build_report_view(storage: Storage, run: Run) -> dict:
    """Готовит данные для страницы отчёта: группы, план действий, дифф."""
    findings = storage.findings_as_models(run.id)
    from ..pages import page_notes
    from ..scoring import group_by_rule

    blocker_groups = group_by_rule([f for f in findings if f.rule == BLOCKER_RULE])
    blockers = [_problem_view(group) for group in blocker_groups]

    groups = []
    for severity, title, key in SEVERITY_GROUPS:
        items = group_by_rule(
            [finding for finding in findings if finding.severity == severity and finding.rule != BLOCKER_RULE]
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
        "total": len(findings),
        "notes": page_notes(run.raw.get("url"), run.raw.get("final_url")),
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
    monitor = Monitor(
        storage,
        scan_options,
        scanner_func=scanner_func or default_scanner,
        notifier=notifier or notify,
    )
    scheduler = Scheduler(monitor, storage, check_interval=check_interval)
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    tasks: set[asyncio.Task] = set()

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

    app = FastAPI(title="webscope", version="0.2.0", lifespan=lifespan)
    app.state.storage = storage
    app.state.monitor = monitor
    app.state.scheduler = scheduler

    # --- страницы ---

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        sites = storage.list_sites()
        cards = []
        for site in sites:
            last = storage.latest_run(site.id)
            cards.append({"site": site, "run": last})
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "sites": cards,
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
    ):
        try:
            normalized = normalize_url(url)
        except ValueError as exc:
            return templates.TemplateResponse(
                request,
                "index.html",
                {
                    "sites": [],
                    "schedules": _SCHEDULE_LABELS,
                    "error": str(exc),
                },
                status_code=400,
            )

        site = storage.add_site(
            normalized,
            email=email.strip() or None,
            telegram_chat=telegram_chat.strip() or None,
            schedule=schedule if schedule in _SCHEDULE_LABELS else "off",
        )
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
    def rescan(site_id: int, background_tasks: BackgroundTasks):
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
    def api_scan(site_id: int, background_tasks: BackgroundTasks):
        site = storage.get_site(site_id)
        if site is None:
            raise HTTPException(status_code=404, detail="Сайт не найден")
        run = trigger(site, background_tasks)
        return JSONResponse({"status": "started", "site_id": site_id, "run_id": run.id}, status_code=202)

    @app.get("/api/sites/{site_id}/report.txt", response_class=PlainTextResponse)
    def api_report_text(site_id: int):
        site = storage.get_site(site_id)
        if site is None:
            raise HTTPException(status_code=404, detail="Сайт не найден")
        last = storage.latest_ok_run(site.id)
        if last is None:
            raise HTTPException(status_code=404, detail="Отчёт ещё не готов")
        return render_plain(_result_from_run(storage, last))

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
