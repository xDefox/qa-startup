"""Pages routes — P1: полное разделение из app.py."""

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ..auth import apply_headers, auth_configured, is_authenticated, unauthorized_response

router = APIRouter(prefix="", tags=["pages"])
TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


def index_cards(storage) -> list:
    return [{"site": item, "run": storage.latest_run(item.id)} for item in storage.list_sites()]


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    # P1: заглушка — требует storage и _SCHEDULE_LABELS
    return TEMPLATES.TemplateResponse(request, "index.html", {"sites": [], "schedules": {}, "error": None})


@router.get("/sites", response_class=HTMLResponse)
async def list_sites(request: Request):
    if auth_configured() and not is_authenticated(request):
        return apply_headers(unauthorized_response(request))
    return TEMPLATES.TemplateResponse(request, "sites.html", {"sites": []})


@router.get("/sites/{site_id}", response_class=HTMLResponse)
async def site_page(request: Request, site_id: int):
    raise HTTPException(status_code=404, detail="Сайт не найден (P1 заглушка)")


@router.get("/sites")
async def sites_index():
    return RedirectResponse(url="/", status_code=303)
