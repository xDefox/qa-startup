"""Auth routes — выделены из app.py (P0 разделение)."""

from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ..auth import (
    COOKIE_NAME,
    auth_configured,
    check_credentials,
    cookie_kwargs,
    login_page,
    session_token,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/login", response_class=HTMLResponse)
async def auth_login_form(request: Request, next: str = "/"):
    if not auth_configured():
        return RedirectResponse(url="/", status_code=303)
    from pathlib import Path

    from fastapi.templating import Jinja2Templates

    templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))
    return login_page(request, templates)


@router.post("/login")
async def auth_login(
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
    templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))
    return login_page(request, templates, error="Неверные логин или пароль")


@router.get("/logout")
async def auth_logout():
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie(key=COOKIE_NAME)
    return response
