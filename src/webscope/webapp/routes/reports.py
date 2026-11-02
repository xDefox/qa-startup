"""Скачивание отчёта в пяти форматах."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from ..deps import get_site_or_404
from ..report_files import (
    REPORT_MEDIA_TYPES,
    REPORT_RENDERERS,
    content_disposition,
    download_filename,
)
from ..state import AppState, get_state
from ..storage import Run, Site
from ..views import result_from_run

router = APIRouter()


def _report_payload(state: AppState, site_id: int, fmt: str) -> tuple[Site, Run, str]:
    """Готовый отчёт: сайт, прогон и содержимое в нужном формате."""
    site = get_site_or_404(state, site_id)
    last = state.storage.latest_ok_run(site.id)
    if last is None:
        raise HTTPException(status_code=404, detail="Отчёт ещё не готов")
    return site, last, REPORT_RENDERERS[fmt](result_from_run(state.storage, last))


def _report_response(state: AppState, site_id: int, fmt: str, download: bool, filename: str | None = None) -> Response:
    """Отчёт для просмотра в браузере или файлом на скачивание.

    ``filename`` — имя, выбранное пользователем в панели сохранения;
    оно чистится (``safe_report_stem``) и попадает в ``Content-Disposition``.
    Заголовок важнее атрибута ``download`` в ссылке, поэтому имя задаётся
    именно здесь, а не в разметке.
    """
    site, run, payload = _report_payload(state, site_id, fmt)
    headers: dict[str, str] = {}
    if download:
        headers["Content-Disposition"] = content_disposition(
            download_filename(site, run, fmt, filename),
            fallback=download_filename(site, run, fmt),
        )
        headers["Cache-Control"] = "no-store"
    return Response(content=payload, media_type=REPORT_MEDIA_TYPES[fmt], headers=headers)


@router.get("/api/sites/{site_id}/report.txt")
def api_report_text(
    site_id: int, state: AppState = Depends(get_state), download: bool = False, filename: str | None = None
):
    return _report_response(state, site_id, "txt", download, filename)


@router.get("/api/sites/{site_id}/report.json")
def api_report_json(
    site_id: int, state: AppState = Depends(get_state), download: bool = False, filename: str | None = None
):
    return _report_response(state, site_id, "json", download, filename)


@router.get("/api/sites/{site_id}/report.html")
def api_report_html(
    site_id: int, state: AppState = Depends(get_state), download: bool = False, filename: str | None = None
):
    return _report_response(state, site_id, "html", download, filename)


@router.get("/api/sites/{site_id}/report.sarif")
def api_report_sarif(
    site_id: int, state: AppState = Depends(get_state), download: bool = False, filename: str | None = None
):
    return _report_response(state, site_id, "sarif", download, filename)


@router.get("/api/sites/{site_id}/report.xml")
def api_report_junit(
    site_id: int, state: AppState = Depends(get_state), download: bool = False, filename: str | None = None
):
    return _report_response(state, site_id, "xml", download, filename)
