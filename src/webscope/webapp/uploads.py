"""Локальные сборки: каталог, лимиты, очистка и раздача в песочнице.

Загруженная страница исполняется на origin приложения, поэтому раздача
закрыта CSP-песочницей, а размеры загрузки ограничены: один прогон не должен
уметь забить диск и не должен тянуть гигабайты в память процесса.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from fastapi.staticfiles import StaticFiles

LOCAL_DIR = Path(tempfile.gettempdir()) / "webscope-local"
LOCAL_DIR.mkdir(parents=True, exist_ok=True)

MAX_UPLOAD_FILES = 300
MAX_UPLOAD_FILE_BYTES = 10 * 1024 * 1024
MAX_UPLOAD_TOTAL_BYTES = 50 * 1024 * 1024
# Сколько последних загрузок храним (остальные удаляются при новой загрузке).
MAX_UPLOAD_JOBS = 50


def prune_local_uploads(keep: int = MAX_UPLOAD_JOBS, directory: Path | None = None) -> None:
    """Удаляет старые загруженные сборки, чтобы каталог не рос бесконечно.

    ``directory`` — каталог загрузок; по умолчанию общий ``LOCAL_DIR``.
    Отдельный параметр нужен тестам: без него пришлось бы подменять
    глобальную переменную модуля.
    """
    directory = directory or LOCAL_DIR
    try:
        jobs = sorted(
            (path for path in directory.iterdir() if path.is_dir()),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
    except OSError:  # каталога нет или нет прав — загрузка всё равно важнее
        return
    for stale in jobs[keep:]:
        shutil.rmtree(stale, ignore_errors=True)


class SandboxedLocalFiles(StaticFiles):
    """Раздача загруженных страниц в песочнице.

    Загруженный HTML исполняется на origin приложения. Без песочницы его скрипт
    читал бы cookie и ходил в `/api` от имени пользователя. Директива CSP
    ``sandbox`` переводит документ в уникальный opaque-origin: скрипты и стили
    самой страницы работают (иначе проверка локальной сборки теряет смысл),
    а доступа к cookie, localStorage и API приложения у них нет.
    """

    SANDBOX = "sandbox allow-scripts allow-forms allow-popups allow-modals"

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        if response.status_code < 400:
            response.headers["Content-Security-Policy"] = self.SANDBOX
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Cache-Control"] = "no-store"
        return response
