"""API routes — выделены из app.py (P1 разделение)."""

from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["api"])
