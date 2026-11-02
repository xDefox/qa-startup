"""Структура веб-приложения: app.py собирает, роутеры обрабатывают.

Раньше всё лежало в одной функции `create_app` на 500 строк: 23 маршрута
и замыкания на хранилище, монитор и лимитер. Добавить маршрут можно было
только туда же, а проверить обработчик отдельно — никак.

Эти тесты держат разбиение: если кто-то снова начнёт писать `@app.get`
в `app.py` или маршрут потеряется при переносе, будет видно сразу.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from webscope.webapp.app import create_app

WEBAPP = Path(__file__).resolve().parents[1] / "src" / "webscope" / "webapp"
ROUTE_MODULES = ("auth", "pages", "api", "reports", "uploads")


HTTP_VERBS = {"get", "post", "put", "patch", "delete", "options", "head"}


def _route_decorators(source: Path) -> list[str]:
    """Имена декораторов вида `@app.get(...)` / `@router.post(...)`.

    `@app.middleware("http")` — не маршрут, поэтому считаем только HTTP-глаголы.
    """
    found: list[str] = []
    tree = ast.parse(source.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
                continue
            if decorator.func.attr not in HTTP_VERBS:
                continue
            owner = decorator.func.value
            if isinstance(owner, ast.Name):
                found.append(f"{owner.id}.{decorator.func.attr}")
    return found


def test_app_module_defines_no_routes() -> None:
    """app.py — сборка, а не свалка обработчиков."""
    assert _route_decorators(WEBAPP / "app.py") == []


def test_app_module_is_small() -> None:
    lines = len((WEBAPP / "app.py").read_text(encoding="utf-8").splitlines())
    assert lines < 200, f"app.py разросся до {lines} строк — выносите обработчики в routes/"


@pytest.mark.parametrize("name", ROUTE_MODULES)
def test_route_module_registers_routes(name: str) -> None:
    """Каждый модуль роутеров что-то объявляет и не тащит FastAPI-приложение."""
    source = WEBAPP / "routes" / f"{name}.py"
    decorators = _route_decorators(source)
    assert decorators, f"routes/{name}.py не объявляет ни одного маршрута"
    assert all(item.startswith("router.") for item in decorators), decorators


@pytest.fixture()
def app(tmp_path: Path, stub_scanner) -> FastAPI:
    return create_app(
        db_path=tmp_path / "db.sqlite",
        scanner_func=stub_scanner,
        notifier=lambda **kw: [],
        local_dir=tmp_path / "local",
    )


def test_all_public_routes_are_mounted(app: FastAPI) -> None:
    """Маршруты из роутеров реально попали в приложение.

    `app.routes` для этого не годится: новые FastAPI держат подключённые
    роутеры ленивой обёрткой `_IncludedRouter`, и плоского списка путей там
    больше нет. OpenAPI-схема собирает то же, что реально обслуживается.
    """
    paths = set(app.openapi()["paths"])
    expected = {
        "/auth/login",
        "/auth/logout",
        "/",
        "/sites",
        "/sites/{site_id}",
        "/sites/{site_id}/scan",
        "/sites/{site_id}/history",
        "/sites/{site_id}/settings",
        "/sites/{site_id}/delete",
        "/healthz",
        "/api/sites",
        "/api/sites/{site_id}",
        "/api/sites/{site_id}/runs",
        "/api/sites/{site_id}/scan",
        "/upload",
        "/api/sites/{site_id}/report.txt",
        "/api/sites/{site_id}/report.json",
        "/api/sites/{site_id}/report.html",
        "/api/sites/{site_id}/report.sarif",
        "/api/sites/{site_id}/report.xml",
    }
    assert expected <= paths, sorted(expected - paths)


def test_state_is_single_source(app: FastAPI) -> None:
    """Состояние лежит под одним ключом, а не разбросано по app.state."""
    state = app.state.webscope
    assert state.storage is not None
    assert state.monitor is not None
    assert state.local_dir.exists()


def test_healthz_works_without_login(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    """Healthcheck обязан отвечать без входа: его дергает внешний мониторинг."""
    monkeypatch.setenv("WEBSCOPE_AUTH_PASSWORD", "secret")
    with TestClient(app) as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
