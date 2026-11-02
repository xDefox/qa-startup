"""Auth routes — выделены из app.py (P0 разделение)."""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from ..auth import (
    COOKIE_NAME,
    cookie_kwargs,
    auth_configured,
    check_credentials,
    is_authenticated,
    login_page,
    session_token,
    unauthorized_response,
)

router = APIRouter(prefix="/auth", tags=["auth"])

@router.get("/login", response_class=HTMLResponse)
async def auth_login_form(request: Request, next: str = "/"):
    if not auth_configured():
        return RedirectResponse(url="/", status_code=303)
    from fastapi.templating import Jinja2Templates
    from pathlib import Path
    templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))
    return login_page(request, templates)

@router.post("/login")
async def auth_login(request: Request):
    # Заглушка: полная реализация в app.py (P0 — разделение)
    return RedirectResponse(url="/", status_code=303)

@router.get("/logout")
async def auth_logout():
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie(key=COOKIE_NAME)
    return response
