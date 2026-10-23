"""Доступность: axe-core.

Движок находок — axe-core 4.11.0 (вендорится в репозиторий, чтобы не тянуть сеть
в рантайме и не зависеть от CDN). Мы добавляем только селектор, сниппет и ссылку
на документацию правила — интерпретацию severity делаем сами по impact.
"""

from __future__ import annotations

from pathlib import Path

from ..context import ScanContext
from ..models import Finding, Severity, severity_from_impact

AXE_PATH = Path(__file__).resolve().parent.parent / "vendor" / "axe.min.js"

AXE_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"]


def run(page: object, ctx: ScanContext) -> list[Finding]:
    if not AXE_PATH.exists():  # pragma: no cover - защита от сборки без vendor/
        return []

    page.add_script_tag(path=str(AXE_PATH))  # type: ignore[attr-defined]
    raw = page.evaluate(  # type: ignore[attr-defined]
        """async (tags) => {
            const result = await axe.run(document, {
                runOnly: { type: 'tag', values: tags },
                resultTypes: ['violations'],
            });
            return result.violations.map((v) => ({
                id: v.id,
                impact: v.impact,
                help: v.help,
                helpUrl: v.helpUrl,
                description: v.description,
                tags: v.tags,
                nodes: v.nodes.slice(0, 5).map((n) => ({
                    target: n.target,
                    html: (n.html || '').slice(0, 300),
                    failureSummary: n.failureSummary || '',
                })),
            }));
        }""",
        AXE_TAGS,
    )

    _AXE_TRANSLATE = {
        "link-in-text-block": "Ссылки нужно отличать от окружающего текста не только цветом",
        "color-contrast": "Недостаточный контраст текста и фона",
        "image-alt": "Изображение без альтернативного текста",
        "button-name": "Кнопка без доступного названия",
        "link-name": "Ссылка без доступного названия",
        "label": "Поле формы без подписи",
        "document-title": "У страницы нет заголовка <title>",
        "html-has-lang": "У <html> не указан язык страницы",
        "landmark-one-main": "На странице нет основного ориентира <main>",
        "region": "Содержимое не размещено в семантических блоках",
        "heading-order": "Неправильный порядок заголовков",
        "frame-title": "У iframe нет заголовка",
        "duplicate-id": "Повторяющиеся id на странице",
        "tabindex": "Некорректное использование tabindex",
    }

    findings: list[Finding] = []
    for violation in raw or []:
        severity = severity_from_impact(violation.get("impact"))
        for node in violation.get("nodes", []):
            targets = node.get("target") or []
            selector = targets[0] if targets else None
            rule_id = violation["id"]
            help = violation.get("help") or rule_id
            if help.startswith(("Ensure", "Elements")):
                help = _AXE_TRANSLATE.get(rule_id, help)
            message = violation.get("description") or ""
            if message.startswith("Ensure") and rule_id == "link-in-text-block":
                message = (
                    "Ссылки должны отличаться от обычного текста не только по цвету — "
                    "добавьте подчеркивание или другой признак."
                )
            findings.append(
                Finding(
                    rule=rule_id,
                    severity=severity,
                    title=help,
                    message=message,
                    url=ctx.final_url,
                    selector=selector,
                    snippet=node.get("html"),
                    help_url=violation.get("helpUrl"),
                    source="webscope.a11y",
                    details={
                        "impact": violation.get("impact"),
                        "wcag": [t for t in violation.get("tags", []) if t.startswith("wcag")],
                        "failureSummary": node.get("failureSummary"),
                    },
                )
            )
    return findings


def severity_for_impact(impact: str | None) -> Severity:
    """Отдельная обёртка — используется в тестах и в отчётах."""
    return severity_from_impact(impact)
