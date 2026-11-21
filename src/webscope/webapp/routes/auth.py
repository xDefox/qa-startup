"""Вход, регистрация и выход."""

from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ..auth import (
    COOKIE_NAME,
    check_credentials,
    cookie_kwargs,
    end_session,
    get_current_user,
    login_page,
    normalize_email,
    register_page,
    safe_next,
    session_token,
    start_session,
    validate_registration,
)
from ..services.site_service import create_organization, get_organizations
from ..state import get_state

router = APIRouter(prefix="/auth", tags=["auth"])


def _client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _too_many(state, request: Request, page: str, **context):
    """Ограничение попыток входа и регистрации с одного адреса."""
    if state.auth_limiter is not None and not state.auth_limiter.allow(_client_key(request)):
        error = "Слишком много попыток. Подождите минуту и попробуйте снова."
        if page == "register":
            return register_page(request, state.templates, error=error, **context)
        return login_page(request, state.templates, error=error)
    return None


def _sign_in(storage, user: dict, request: Request, target: str) -> RedirectResponse:
    token = start_session(storage, user, request)
    response = RedirectResponse(url=target, status_code=303)
    response.set_cookie(value=token, **cookie_kwargs(request))
    return response


@router.get("/login", response_class=HTMLResponse)
async def auth_login_form(request: Request, next: str = ""):
    state = get_state(request)
    if get_current_user(request) is not None:
        return RedirectResponse(url=safe_next(next), status_code=303)
    return login_page(request, state.templates, next_url=safe_next(next, ""))


@router.post("/login")
async def auth_login(
    request: Request,
    email: str = Form(""),
    password: str = Form(""),
    next: str = Form(""),
):
    state = get_state(request)
    limited = _too_many(state, request, "login")
    if limited is not None:
        return limited

    storage = state.storage
    user = storage.verify_user_password(normalize_email(email), password)
    if user is not None:
        return _sign_in(storage, user, request, safe_next(next))

    # Аварийный вход по паролю из окружения (старые установки и восстановление).
    if check_credentials(email, password):
        response = RedirectResponse(url=safe_next(next), status_code=303)
        response.set_cookie(value=session_token(), **cookie_kwargs(request))
        return response

    return login_page(
        request,
        state.templates,
        error="Неверный email или пароль",
        next_url=safe_next(next, ""),
    )


@router.get("/register", response_class=HTMLResponse)
async def auth_register_form(request: Request):
    state = get_state(request)
    if get_current_user(request) is not None:
        return RedirectResponse(url="/dashboard", status_code=303)
    return register_page(request, state.templates)


@router.post("/register")
async def auth_register(
    request: Request,
    email: str = Form(""),
    password: str = Form(""),
    password_confirm: str = Form(""),
):
    state = get_state(request)
    email = normalize_email(email)
    limited = _too_many(state, request, "register", email=email)
    if limited is not None:
        return limited

    error = validate_registration(email, password, password_confirm)
    if error:
        return register_page(request, state.templates, error=error, email=email)

    storage = state.storage
    if storage.user_exists(email):
        return register_page(
            request,
            state.templates,
            error="Пользователь с таким email уже зарегистрирован",
            email=email,
        )

    first_user = storage.count_users() == 0
    user_id = storage.create_user(email, password)
    if first_user:
        # Данные, созданные до появления входа, переходят первому пользователю.
        storage.adopt_orphan_data(user_id)

    orgs = get_organizations(storage, owner_id=user_id)
    if orgs:
        org = orgs[0]
        if first_user and not org.owner_email:
            with storage._conn() as conn:
                conn.execute(
                    "UPDATE organizations SET name = ?, owner_email = ? WHERE id = ?",
                    ("Личный кабинет", email, org.id),
                )
                conn.commit()
    else:
        org = create_organization(
            storage,
            name="Личный кабинет",
            owner_email=email,
            owner_id=user_id,
        )
    storage.set_user_organization(user_id, org.id)

    user = storage.get_user_by_id(user_id)
    if user is None:  # pragma: no cover — возможно только при сбое БД
        return register_page(request, state.templates, error="Не удалось создать аккаунт", email=email)
    return _sign_in(storage, user, request, "/dashboard")


@router.get("/logout")
async def auth_logout(request: Request):
    state = get_state(request)
    end_session(state.storage, request)
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie(key=COOKIE_NAME)
    return response
