"""Загрузка локальной сборки: проверка путей, лимиты, стартовый файл."""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Request, UploadFile

from .. import uploads
from ..deps import scan_limit_response, trigger
from ..state import AppState, get_state
from ..urls import normalize_url

router = APIRouter()


@router.post("/upload")
async def upload_files(
    request: Request,
    state: AppState = Depends(get_state),
    files: list[UploadFile] = File(...),
    paths: list[str] = Form(...),
    background_tasks: BackgroundTasks = None,
):
    limited = scan_limit_response(state, request)
    if limited is not None:
        return limited
    if not files:
        raise HTTPException(status_code=400, detail="Нет файлов")
    if len(files) > uploads.MAX_UPLOAD_FILES:
        raise HTTPException(status_code=413, detail=f"Слишком много файлов (максимум {uploads.MAX_UPLOAD_FILES})")
    if len(paths) != len(files):
        raise HTTPException(status_code=400, detail="Число путей не совпадает с числом файлов")

    job_id = uuid.uuid4().hex
    base = state.local_dir / job_id
    base.mkdir(parents=True, exist_ok=True)
    total_bytes = 0
    try:
        for f, raw_path in zip(files, paths):
            # Абсолютный путь или выход за пределы каталога загрузки —
            # отказ. Раньше фильтр выбрасывал только «..», а «/etc/passwd»
            # оставался абсолютным и записывался мимо каталога задания.
            relative = Path((raw_path or "").replace("\\", "/"))
            if relative.is_absolute():
                raise HTTPException(status_code=400, detail="Абсолютный путь файла не допускается")
            safe = Path(*[part for part in relative.parts if part not in ("..", ".", "")])
            if not safe.parts:
                safe = Path(Path(f.filename or "index.html").name)
            dest = (base / safe).resolve()
            if not dest.is_relative_to(base.resolve()):
                raise HTTPException(status_code=400, detail="Недопустимый путь файла")
            content = await f.read(uploads.MAX_UPLOAD_FILE_BYTES + 1)
            total_bytes += len(content)
            if len(content) > uploads.MAX_UPLOAD_FILE_BYTES or total_bytes > uploads.MAX_UPLOAD_TOTAL_BYTES:
                raise HTTPException(status_code=413, detail="Загруженные файлы слишком большие")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(content)
    except HTTPException:
        shutil.rmtree(base, ignore_errors=True)
        raise

    uploads.prune_local_uploads(keep=uploads.MAX_UPLOAD_JOBS, directory=state.local_dir)
    # выбираем стартовый файл
    index = base / "index.html"
    if not index.exists():
        candidates = list(base.rglob("index.html"))
        if candidates:
            index = candidates[0]
        else:
            htmls = list(base.rglob("*.html"))
            index = htmls[0] if htmls else (base / "index.html")
    rel_idx = index.relative_to(base)
    # Адрес берём из реального запроса (host:port), а не из env — файлы
    # раздаёт это же приложение, и сканер должен ходить туда же.
    origin = str(request.base_url).rstrip("/")
    url = f"{origin}/__local/{job_id}/{rel_idx.as_posix()}"
    try:
        normalized = normalize_url(url)
    except ValueError:
        normalized = url
    site = state.storage.add_site(normalized, email=None, telegram_chat=None, schedule="off")
    trigger(state, site, background_tasks)
    return {"url": normalized, "site_id": site.id}
