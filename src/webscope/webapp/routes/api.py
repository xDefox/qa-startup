"""JSON API: список сайтов, находки, прогоны, запуск проверки."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import JSONResponse

from ..deps import get_site_or_404, scan_limit_response, trigger
from ..state import AppState, get_state

router = APIRouter()


@router.get("/healthz")
def healthz():
    return {"status": "ok"}


@router.get("/api/sites")
def api_sites(state: AppState = Depends(get_state)):
    payload = []
    for site in state.storage.list_sites():
        last = state.storage.latest_ok_run(site.id)
        payload.append(
            {
                **site.to_dict(),
                "last_run": last.to_dict() if last else None,
                "score": last.score if last else None,
            }
        )
    return {"sites": payload}


@router.get("/api/sites/{site_id}")
def api_site(site_id: int, state: AppState = Depends(get_state)):
    site = get_site_or_404(state, site_id)
    last = state.storage.latest_ok_run(site.id)
    newest = state.storage.latest_run(site.id)
    findings = state.storage.findings_of(last.id) if last else []
    diff = state.storage.diff_with_previous(last) if last else None
    return {
        "site": site.to_dict(),
        "last_run": last.to_dict() if last else None,
        "last_error": newest.error if newest and newest.status == "error" else None,
        "findings": [finding.to_dict() for finding in findings],
        "diff": diff.to_dict() if diff else None,
    }


@router.get("/api/sites/{site_id}/runs")
def api_runs(site_id: int, state: AppState = Depends(get_state)):
    site = get_site_or_404(state, site_id)
    return {"runs": [run.to_dict() for run in state.storage.list_runs(site.id, limit=100)]}


@router.post("/api/sites/{site_id}/scan")
def api_scan(request: Request, site_id: int, background_tasks: BackgroundTasks, state: AppState = Depends(get_state)):
    limited = scan_limit_response(state, request)
    if limited is not None:
        return limited
    site = get_site_or_404(state, site_id)
    run = trigger(state, site, background_tasks)
    return JSONResponse({"status": "started", "site_id": site_id, "run_id": run.id}, status_code=202)
"""API routes — выделены из app.py (P1 разделение)."""

from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["api"])
