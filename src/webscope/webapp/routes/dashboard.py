"""Дашборд пользователя: мои сайты, настройки, API ключи."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ..deps import get_current_user, index_cards
from ..services.site_service import get_organizations
from ..state import AppState, get_state

router = APIRouter(tags=["dashboard"])


def _page(state: AppState, request: Request, template: str, context: dict):
    """Рендер шаблона."""
    return state.templates.TemplateResponse(request, template, context)


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_index(
    request: Request,
    state: AppState = Depends(get_state),
    user: dict = Depends(get_current_user),
):
    orgs = get_organizations(state.storage)
    cards = index_cards(state)
    return _page(
        state, request, "dashboard.html",
        {"user": user, "cards": cards, "organizations": orgs, "active_tab": "sites"},
    )


@router.get("/dashboard/settings", response_class=HTMLResponse)
async def dashboard_settings(
    request: Request,
    state: AppState = Depends(get_state),
    user: dict = Depends(get_current_user),
):
    return _page(state, request, "dashboard_settings.html", {"user": user, "active_tab": "settings"})


@router.get("/dashboard/api-keys", response_class=HTMLResponse)
async def dashboard_api_keys(
    request: Request,
    state: AppState = Depends(get_state),
    user: dict = Depends(get_current_user),
):
    return _page(state, request, "dashboard_api_keys.html", {"user": user, "active_tab": "api_keys"})


@router.get("/dashboard/organizations", response_class=HTMLResponse)
async def dashboard_organizations(
    request: Request,
    state: AppState = Depends(get_state),
    user: dict = Depends(get_current_user),
):
    orgs = get_organizations(state.storage)
    return _page(state, request, "dashboard_organizations.html", {"user": user, "organizations": orgs, "active_tab": "organizations"})