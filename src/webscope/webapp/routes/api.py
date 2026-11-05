"""JSON API: список сайтов, находки, прогоны, запуск проверки."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request
from fastapi.responses import JSONResponse

from ...scoring import is_false_positive
from ..deps import get_site_or_404, scan_limit_response, trigger
from ..services.site_service import create_organization, get_organizations
from ..services.site_service import list_sites as list_sites_service
from ..state import AppState, get_state

router = APIRouter(tags=["api"])


@router.get("/api/sites")
def api_sites(
    state: AppState = Depends(get_state),
    organization_id: int | None = Query(None, alias="org_id"),
):
    """Список сайтов с опциональной фильтрацией по организации."""
    sites = list_sites_service(state.storage, organization_id=organization_id)
    payload = []
    for site in sites:
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
    # Исключаем FP из API
    findings = [f for f in findings if not is_false_positive(f)]
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
def api_scan(
    request: Request,
    site_id: int,
    background_tasks: BackgroundTasks,
    state: AppState = Depends(get_state),
):
    limited = scan_limit_response(state, request)
    if limited is not None:
        return limited
    site = get_site_or_404(state, site_id)
    run = trigger(state, site, background_tasks)
    return JSONResponse(
        {"status": "started", "site_id": site_id, "run_id": run.id}, status_code=202
    )


@router.get("/api/organizations")
def api_organizations(state: AppState = Depends(get_state)):
    """Список организаций для UI селектора."""
    orgs = get_organizations(state.storage)
    return {"organizations": [{"id": o.id, "name": o.name, "owner_email": o.owner_email, "created_at": o.created_at} for o in orgs]}


@router.post("/api/organizations")
async def api_create_organization(request: Request, state: AppState = Depends(get_state)):
    """Создаёт новую организацию."""
    body = await request.json()
    name = body.get("name", "").strip()
    owner_email = body.get("owner_email", "").strip()
    if not name:
        return JSONResponse({"detail": "Название обязательно"}, status_code=400)
    org = create_organization(state.storage, name=name, owner_email=owner_email)
    return {"id": org.id, "name": org.name, "owner_email": org.owner_email, "created_at": org.created_at}


@router.patch("/api/organizations/{org_id}")
async def api_update_organization(org_id: int, request: Request, state: AppState = Depends(get_state)):
    """Обновляет организацию."""
    body = await request.json()
    name = body.get("name", "").strip()
    owner_email = body.get("owner_email", "").strip()
    if not name:
        return JSONResponse({"detail": "Название обязательно"}, status_code=400)
    with state.storage._conn() as conn:
        conn.execute(
            "UPDATE organizations SET name = ?, owner_email = ? WHERE id = ?",
            (name, owner_email, org_id)
        )
        conn.commit()
    return {"status": "ok", "org_id": org_id}


@router.delete("/api/organizations/{org_id}")
def api_delete_organization(org_id: int, state: AppState = Depends(get_state)):
    """Удаляет организацию (если нет привязанных сайтов)."""
    # Проверяем, есть ли сайты в организации
    sites = list_sites_service(state.storage, organization_id=org_id)
    if sites:
        return JSONResponse({"detail": "Нельзя удалить организацию с сайтами"}, status_code=400)
    with state.storage._conn() as conn:
        conn.execute("DELETE FROM organizations WHERE id = ?", (org_id,))
        conn.commit()
    return {"status": "ok"}


@router.post("/api/findings/{finding_id}/fp")
async def api_mark_fp(finding_id: int, request: Request, state: AppState = Depends(get_state)):
    """Помечает находку как ложное срабатывание (FP) или снимает пометку."""
    body = await request.json()
    fp = body.get("fp", True)
    state.storage.mark_finding_fp(finding_id, fp)
    return {"status": "ok", "finding_id": finding_id, "fp": fp}
