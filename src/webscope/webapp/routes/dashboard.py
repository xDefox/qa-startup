"""Кабинет: мои сайты, организации, аккаунт и интеграции."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from ..auth import COOKIE_NAME
from ..deps import get_current_user, index_cards
from ..services.site_service import get_organizations
from ..state import AppState, get_state
from ..views import SCHEDULE_OPTIONS

router = APIRouter(tags=["dashboard"])


def _page(state: AppState, request: Request, template: str, context: dict):
    return state.templates.TemplateResponse(request, template, context)


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_index(
    request: Request,
    state: AppState = Depends(get_state),
    user: dict = Depends(get_current_user),
):
    cards = index_cards(state, user["id"])
    summary = {
        "total": len(cards),
        "ok": sum(1 for card in cards if card.run and card.run.status == "ok"),
        "failed": sum(1 for card in cards if card.run and card.run.status == "error"),
        "pending": sum(1 for card in cards if card.run and card.run.status == "running"),
    }
    return _page(
        state,
        request,
        "dashboard.html",
        {
            "user": user,
            "cards": cards,
            "summary": summary,
            "organizations": get_organizations(state.storage, owner_id=user["id"]),
            "schedule_options": SCHEDULE_OPTIONS,
            "active_tab": "sites",
        },
    )


@router.get("/dashboard/settings", response_class=HTMLResponse)
async def dashboard_settings(
    request: Request,
    state: AppState = Depends(get_state),
    user: dict = Depends(get_current_user),
):
    return _page(
        state,
        request,
        "dashboard_settings.html",
        {
            "user": user,
            "active_tab": "settings",
        },
    )


@router.get("/dashboard/api-keys", response_class=HTMLResponse)
async def dashboard_api_keys(
    request: Request,
    state: AppState = Depends(get_state),
    user: dict = Depends(get_current_user),
):
    """Интеграции: вебхуки и REST API. Ключей доступа в этой версии нет."""
    return _page(
        state,
        request,
        "dashboard_integrations.html",
        {
            "user": user,
            "base_url": str(request.base_url).rstrip("/"),
            "cookie_name": COOKIE_NAME,
            "active_tab": "api_keys",
        },
    )


@router.get("/dashboard/organizations", response_class=HTMLResponse)
async def dashboard_organizations(
    request: Request,
    state: AppState = Depends(get_state),
    user: dict = Depends(get_current_user),
):
    orgs = get_organizations(state.storage, owner_id=user["id"])
    return _page(
        state,
        request,
        "dashboard_organizations.html",
        {
            "user": user,
            "organizations": orgs,
            "active_tab": "organizations",
        },
    )
