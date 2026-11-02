"""Pages routes — выделены из app.py (P1 разделение)."""
from fastapi import APIRouter

router = APIRouter(prefix="", tags=["pages"])

# Заглушки для разделения — функции перенесены из app.py
@router.get("/")
async def index():
    pass

# Перенесено из app.py (P0 разделение)
# index_cards(), index(), sites_index(), site_page(), site_history(), site_settings()
# site_settings_save(), site_delete() — заглушки, требуют полной реализации
