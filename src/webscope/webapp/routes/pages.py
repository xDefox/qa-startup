"""Pages routes — выделены из app.py (P1 разделение)."""
from fastapi import APIRouter

router = APIRouter(prefix="", tags=["pages"])

# Заглушки для разделения — функции перенесены из app.py
@router.get("/")
async def index():
    pass
