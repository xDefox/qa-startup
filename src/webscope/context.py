"""Контекст сканирования: то, что доступно всем проверкам."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ScanContext:
    """Данные, собранные браузером до запуска проверок."""

    url: str
    final_url: str
    title: str
    archetype: dict[str, Any] = field(default_factory=dict)
    console_messages: list[dict[str, str]] = field(default_factory=list)
    failed_requests: list[dict[str, Any]] = field(default_factory=list)
    evidence_dir: Path | None = None
    timeout_ms: int = 30_000
    max_link_checks: int = 20
    notes: list[str] = field(default_factory=list)

    def evidence_path(self, name: str) -> Path | None:
        """Путь для сохранения evidence-файла (None, если evidence выключена)."""
        if self.evidence_dir is None:
            return None
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        return self.evidence_dir / name
