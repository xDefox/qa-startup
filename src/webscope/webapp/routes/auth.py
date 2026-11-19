"""Auth routes."""

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ..auth import (
    COOKIE_NAME,
    auth_configured,
    _make_db_cookie,
    check_credentials,
    cookie_kwargs,
    login_page,
    register_page,
    session_token,
)
from ..state import get_state

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/login", response_class=HTMLResponse)
async def auth_login_form(request: Request, next: str = "/"):
    state = get_state(request)
    if not auth_configured(state.storage):
        return RedirectResponse(url="/", status_code=303)
    return login_page(request, state.templates)


@router.post("/login")
async def auth_login(request: Request, username: str = Form(""), password: str = Form(""), next: str = Form("/")):
    state = get_state(request)
    if not auth_configured(state.storage):
        return RedirectResponse(url="/", status_code=303)
    state = get_state(request)
    storage = state.storage
    # Try DB user first
    user = storage.verify_user_password(username, password)
    if user:
        token = _make_db_cookie(user["id"], user["password_hash"])
        target = next if next.startswith("/") and not next.startswith("//") else "/"
        response = RedirectResponse(url=target, status_code=303)
        response.set_cookie(value=token, **cookie_kwargs(request))
        return response
    # Fall back to env
    if check_credentials(username, password):
        target = next if next.startswith("/") and not next.startswith("//") else "/"
        response = RedirectResponse(url=target, status_code=303)
        response.set_cookie(value=session_token(), **cookie_kwargs(request))
        return response
    return login_page(request, state.templates, error="Неверные логин или пароль")


@router.get("/logout")
async def auth_logout():
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie(key=COOKIE_NAME)
    return response


@router.get("/register", response_class=HTMLResponse)
async def auth_register_form(request: Request):
    state = get_state(request)
    # Регистрация всегда доступна (первый пользователь создаёт аккаунт)
    return register_page(request, state.templates)


@router.post("/register")
async def auth_register(request: Request, email: str = Form(""), password: str = Form(""), password_confirm: str = Form("")):
    # Регистрация доступна всегда (первый пользователь создаёт аккаунт)
    state = get_state(request)
    storage = state.storage
    email = email.strip().lower()
    if not email or "@" not in email:
        return register_page(request, state.templates, error="Введите корректный email")
    if len(password) < 8:
        return register_page(request, state.templates, error="Пароль должен быть не менее 8 символов")
    if password != password_confirm:
        return register_page(request, state.templates, error="Пароли не совпадают")
    if storage.user_exists(email):
        return register_page(request, state.templates, error="Пользователь с таким email уже существует")
    # Create user
    user_id = storage.create_user(email, password, organization_id=0)
    user = storage.get_user_by_id(user_id)
    token = _make_db_cookie(user["id"], user["password_hash"])
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(value=token, **cookie_kwargs(request))
    return response