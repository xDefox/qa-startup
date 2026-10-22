"""Веб-обёртка webscope: сайт для владельца, история прогонов, алерты."""

from __future__ import annotations

__all__ = ["create_app"]


def __getattr__(name: str):  # pragma: no cover - ленивый импорт
    if name == "create_app":
        from .app import create_app

        return create_app
    raise AttributeError(name)
