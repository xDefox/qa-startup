from __future__ import annotations

from ...context import ScanContext
from ...models import Finding
from . import base, validation


def run(page: object, ctx: ScanContext) -> list[Finding]:
    findings: list[Finding] = []
    findings.extend(base.run(page, ctx))
    findings.extend(validation.run(page, ctx))
    return findings
