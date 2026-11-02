"""HTML-страницы: главная, отчёт, история, настройки."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ..deps import get_site_or_404, index_cards, scan_limit_response, trigger
from ..forms import auth_fields
from ..report_files import DOWNLOAD_FORMATS, default_report_stem, download_filename, human_date
from ..state import AppState, get_state
from ..urls import normalize_url
from ..views import SCHEDULE_LABELS, build_report_view

router = APIRouter()


def _page(state: AppState, request: Request, template: str, context: dict, **kwargs):
    """Отрисовка шаблона с ленивым импортом Jinja2Templates только для типов."""
    return state.templates.TemplateResponse(request, template, context, **kwargs)


@router.get("/", response_class=HTMLResponse)
def index(request: Request, state: AppState = Depends(get_state)):
    return _page(
        state,
        request,
        "index.html",
        {
            "sites": index_cards(state),
            "schedules": SCHEDULE_LABELS,
            "error": None,
        },
    )


@router.post("/sites")
def create_site(
    request: Request,
    background_tasks: BackgroundTasks,
    state: AppState = Depends(get_state),
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
    limited = scan_limit_response(state, request)
    if limited is not None:
        return limited

    try:
        normalized = normalize_url(url)
    except ValueError as exc:
        return _page(
            state,
            request,
            "index.html",
            {
                "sites": index_cards(state),
                "schedules": SCHEDULE_LABELS,
                "error": str(exc),
            },
            status_code=400,
        )

    if auth_enabled and not auth_login.strip():
        return _page(
            state,
            request,
            "index.html",
            {
                "sites": index_cards(state),
                "schedules": SCHEDULE_LABELS,
                "error": "Включена авторизация, но не указан логин.",
            },
            status_code=400,
        )

    auth = auth_fields(
        enabled=auth_enabled,
        kind=auth_kind,
        login=auth_login,
        password=auth_password,
        login_url=auth_login_url,
    )
    site = state.storage.add_site(
        normalized,
        email=email.strip() or None,
        telegram_chat=telegram_chat.strip() or None,
        schedule=schedule if schedule in SCHEDULE_LABELS else "off",
        **auth,
    )
    if auth["auth_kind"] is not None:
        # URL мог быть уже известен, а add_site существующую строку не трогает:
        # форма с галочкой — источник актуальных кредов, дописываем их.
        # Галочка выключена — вход не трогаем, чтобы перепроверка без неё
        # не чистила настроенные ранее креды.
        state.storage.update_site(site.id, **auth)
    trigger(state, site, background_tasks)
    return RedirectResponse(url=f"/sites/{site.id}", status_code=303)


@router.get("/sites")
def sites_index():
    """Список сайтов живёт на главной; /sites — адрес после входа."""
    return RedirectResponse(url="/", status_code=303)


@router.get("/sites/{site_id}", response_class=HTMLResponse)
def site_page(request: Request, site_id: int, state: AppState = Depends(get_state)):
    site = get_site_or_404(state, site_id)

    pending = state.storage.running_run(site.id)
    last = state.storage.latest_ok_run(site.id)
    newest = state.storage.latest_run(site.id)
    last_error = newest.error if newest and newest.status == "error" else None
    view = build_report_view(state.storage, last) if last else None
    return _page(
        state,
        request,
        "site.html",
        {
            "site": site,
            "view": view,
            "pending": pending,
            "last_error": last_error,
            "schedule_label": SCHEDULE_LABELS.get(site.schedule, site.schedule),
            "download_formats": DOWNLOAD_FORMATS,
            "download_sample": download_filename(site, last, "json") if last else None,
            "download_default_name": default_report_stem(site, last) if last else None,
            "download_date": human_date(last.started_at) if last else None,
        },
    )


@router.post("/sites/{site_id}/scan")
def rescan(request: Request, site_id: int, background_tasks: BackgroundTasks, state: AppState = Depends(get_state)):
    limited = scan_limit_response(state, request)
    if limited is not None:
        return limited
    site = get_site_or_404(state, site_id)
    trigger(state, site, background_tasks)
    return RedirectResponse(url=f"/sites/{site.id}", status_code=303)


@router.get("/sites/{site_id}/history", response_class=HTMLResponse)
def site_history(request: Request, site_id: int, state: AppState = Depends(get_state)):
    site = get_site_or_404(state, site_id)
    runs = [run for run in state.storage.list_runs(site.id, limit=60) if run.status == "ok"]
    counts = state.storage.severity_counts([run.id for run in runs])
    return _page(state, request, "history.html", {"site": site, "runs": runs, "counts": counts})


@router.get("/sites/{site_id}/settings", response_class=HTMLResponse)
def site_settings(request: Request, site_id: int, state: AppState = Depends(get_state), saved: bool = False):
    site = get_site_or_404(state, site_id)
    return _page(
        state,
        request,
        "settings.html",
        {
            "site": site,
            "schedules": SCHEDULE_LABELS,
            "saved": saved,
        },
    )


@router.post("/sites/{site_id}/settings")
def site_settings_save(
    site_id: int,
    state: AppState = Depends(get_state),
    email: str = Form(""),
    telegram_chat: str = Form(""),
    schedule: str = Form("off"),
    auth_enabled: str = Form(""),
    auth_kind: str = Form("basic"),
    auth_login: str = Form(""),
    auth_password: str = Form(""),
    auth_login_url: str = Form(""),
):
    site = get_site_or_404(state, site_id)
    schedule = schedule if schedule in SCHEDULE_LABELS else "off"
    state.storage.update_site(
        site.id,
        email=email.strip() or None,
        telegram_chat=telegram_chat.strip() or None,
        schedule=schedule,
        **auth_fields(
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
    updated = state.storage.get_site(site.id)
    if updated is not None:
        state.monitor.schedule_next(updated)
    return RedirectResponse(url=f"/sites/{site.id}/settings?saved=1", status_code=303)


@router.post("/sites/{site_id}/delete")
def site_delete(site_id: int, state: AppState = Depends(get_state)):
    if not state.storage.delete_site(site_id):
        raise HTTPException(status_code=404, detail="Сайт не найден")
    return RedirectResponse(url="/", status_code=303)
