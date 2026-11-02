"""Вход в интерфейс: форма, проверка пароля, выход."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ..auth import (
    COOKIE_NAME,
    auth_configured,
    check_credentials,
    cookie_kwargs,
    login_page,
    session_token,
)
from ..state import AppState, get_state

router = APIRouter()


@router.get("/auth/login", response_class=HTMLResponse)
def auth_login_form(request: Request, state: AppState = Depends(get_state), next: str = "/"):
    if not auth_configured():
        return RedirectResponse(url="/", status_code=303)
    return login_page(request, state.templates)


@router.post("/auth/login")
def auth_login(
    request: Request,
    state: AppState = Depends(get_state),
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
    return login_page(request, state.templates, error="Неверные логин или пароль")


@router.get("/auth/logout")
def auth_logout():
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie(key=COOKIE_NAME)
    return response
