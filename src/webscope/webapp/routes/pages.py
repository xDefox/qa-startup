"""Pages routes — выделены из app.py (P1 разделение)."""

from fastapi import APIRouter

router = APIRouter(prefix="", tags=["pages"])


# Заглушки для разделения — функции перенесены из app.py
# index_cards(), index(), sites_index(), site_page(), site_history(), site_settings()
# site_settings_save(), site_delete() — заглушки, требуют полной реализации


# Перенесено из app.py (P0 разделение)
# index_cards(), index(), sites_index(), site_page(), site_history(), site_settings()
# site_settings_save(), site_delete() — заглушки, требуют полной реализации

# P0: перенесено из app.py

from fastapi import Request
from fastapi.responses import HTMLResponse

# Заглушка: реальная реализация требует доступа к storage, templates, limiter
# и другим объектам из app.py


def index_cards():
    return []  # заглушка


def index(request: Request):
    return HTMLResponse("Главная — заглушка (перенос в процессе)")


def list_sites(request: Request):
    return HTMLResponse("Сайты — заглушка (перенос в процессе)")
