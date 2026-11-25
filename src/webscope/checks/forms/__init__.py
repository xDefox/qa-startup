from __future__ import annotations

from ...context import ScanContext
from ...models import Finding
from . import base


def run(page: object, ctx: ScanContext) -> list[Finding]:
    """Формы: только подтверждённые поломки отправки и потери полей."""
    return base.run(page, ctx)
