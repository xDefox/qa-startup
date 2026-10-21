"""Формирование отчётов: текст, JSON, HTML, SARIF, JUnit и fix-prompt для агента."""

from __future__ import annotations

import html as html_lib
import json
from typing import Any

from .models import Finding, ScanResult, Severity

SEVERITY_LABEL = {
    Severity.CRITICAL: "CRITICAL",
    Severity.SERIOUS: "SERIOUS",
    Severity.MODERATE: "MODERATE",
    Severity.MINOR: "MINOR",
}

# Критерий приёмки по правилу — то, что агент должен проверить после фикса.
ACCEPTANCE: dict[str, str] = {
    "content/missing-lang": 'У <html> есть атрибут lang со значением BCP-47, например lang="ru".',
    "content/missing-title": "У документа есть непустой <title>.",
    "content/missing-description": 'В <head> есть <meta name="description" content="..."> с описанием страницы.',
    "content/missing-viewport": 'Есть <meta name="viewport" content="width=device-width, initial-scale=1">.',
    "content/missing-charset": 'В <head> есть <meta charset="utf-8"> — кодировка страницы задана явно.',
    "content/no-h1": "На странице ровно один <h1> с осмысленным текстом.",
    "content/multiple-h1": "На странице остался один <h1>.",
    "content/heading-order": "Уровни заголовков идут без пропусков (h2 -> h3, не h2 -> h4).",
    "content/image-alt": 'У изображения непустой alt (или alt="" с role="presentation" для декоративного).',
    "content/iframe-title": "У iframe есть непустой title.",
    "content/empty-link-name": "У ссылки есть осмысленный текст или aria-label.",
    "content/empty-button-name": "У кнопки есть текст или aria-label.",
    "content/duplicate-id": "id на странице уникальны.",
    "forms/control-without-label": "У поля есть <label for> (или aria-label/aria-labelledby).",
    "forms/placeholder-as-label": "У поля есть постоянная подпись <label>, а не только placeholder.",
    "forms/control-without-name": "У поля есть атрибут name, значение отправляется в форму.",
    "forms/email-without-autocomplete": 'У email-поля есть autocomplete="email".',
    "forms/submit-without-accessible-name": "У кнопки есть текст или aria-label.",
    "links/empty-href": "У ссылки реальный href либо обработчик с корректной семантикой (кнопка).",
    "links/target-blank-noopener": 'У ссылки с target="_blank" есть rel="noopener".',
    "links/mixed-content": "Все ресурсы страницы загружаются по https.",
    "links/broken": "Ссылка ведёт на страницу с HTTP-статусом < 400.",
    "links/unreachable": "Ссылка открывается.",
    "console/error": "В консоли нет ошибок.",
    "console/warning": "В консоли нет предупреждений.",
    "console/failed-request": "Все ресурсы страницы загружаются без ошибок.",
    "viewport/horizontal-overflow": "При ширине 320px нет горизонтальной прокрутки.",
    "viewport/overflowing-element": "Элемент не выходит за границу окна.",
    "viewport/target-size": "Цель касания не меньше 24×24 px.",
}


def acceptance_for(finding: Finding) -> str:
    """Критерий приёмки для правила (с запасным вариантом)."""
    if finding.rule in ACCEPTANCE:
        return ACCEPTANCE[finding.rule]
    return "Проверка проходит повторный прогон webscope без этой находки."


def render_text(result: ScanResult) -> str:
    """Человекочитаемый отчёт для терминала."""
    summary = result.summary
    lines: list[str] = []
    lines.append(f"webscope: {result.final_url or result.url}")
    if result.title:
        lines.append(f"title:    {result.title}")
    archetype = result.archetype or {}
    stack = ", ".join(filter(None, [archetype.get("framework"), archetype.get("cms"), archetype.get("ui_kit")]))
    if stack:
        lines.append(f"stack:    {stack}")
    lines.append(f"time:     {result.duration_ms} ms")
    lines.append("")
    lines.append(
        "найдено:  "
        + f"critical={summary['critical']} serious={summary['serious']} "
        + f"moderate={summary['moderate']} minor={summary['minor']} total={summary['total']}"
    )

    if not result.findings:
        lines.append("")
        lines.append("Проблем не найдено.")
        return "\n".join(lines)

    lines.append("")
    for index, finding in enumerate(result.findings, start=1):
        location = f"{finding.url}"
        if finding.selector:
            location += f" → {finding.selector}"
        lines.append(f"{index:>3}. [{SEVERITY_LABEL[finding.severity]}] {finding.title}")
        lines.append(f"     rule:    {finding.rule}")
        lines.append(f"     where:   {location}")
        if finding.message:
            lines.append(f"     why:     {finding.message}")
        if finding.snippet:
            lines.append(f"     snippet: {finding.snippet[:160]}")
        if finding.help_url:
            lines.append(f"     docs:    {finding.help_url}")
        lines.append("")

    return "\n".join(lines)


def render_json(result: ScanResult) -> str:
    return json.dumps(result.to_dict(), ensure_ascii=False, indent=2)


def render_sarif(result: ScanResult) -> str:
    """SARIF — формат, который понимают GitHub Code Scanning и IDE."""
    rules: dict[str, dict[str, Any]] = {}
    results: list[dict[str, Any]] = []

    for finding in result.findings:
        rules.setdefault(
            finding.rule,
            {
                "id": finding.rule,
                "name": finding.rule,
                "shortDescription": {"text": finding.title},
                "helpUri": finding.help_url or "https://github.com/webscope/webscope",
                "defaultConfiguration": {"level": _sarif_level(finding.severity)},
            },
        )
        region = {}
        if finding.snippet:
            region["snippet"] = {"text": finding.snippet}
        results.append(
            {
                "ruleId": finding.rule,
                "level": _sarif_level(finding.severity),
                "message": {"text": finding.message or finding.title},
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {"uri": finding.url},
                            **({"region": region} if region else {}),
                        }
                    }
                ],
            }
        )

    return json.dumps(
        {
            "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
            "version": "2.1.0",
            "runs": [
                {
                    "tool": {
                        "driver": {
                            "name": "webscope",
                            "informationUri": "https://github.com/webscope/webscope",
                            "rules": list(rules.values()),
                        }
                    },
                    "results": results,
                }
            ],
        },
        ensure_ascii=False,
        indent=2,
    )


def _sarif_level(severity: Severity) -> str:
    return {
        Severity.CRITICAL: "error",
        Severity.SERIOUS: "error",
        Severity.MODERATE: "warning",
        Severity.MINOR: "note",
    }[severity]


def render_junit(result: ScanResult) -> str:
    """JUnit XML — для CI-агрегаторов (Allure, TeamCity, Jenkins)."""
    summary = result.summary
    cases: list[str] = []
    for finding in result.findings:
        cases.append(
            f'    <testcase classname="webscope.{html_lib.escape(finding.rule)}" name="{html_lib.escape(finding.title)}">\n'
            f'      <failure message="{html_lib.escape(finding.message or finding.title)}" type="{finding.severity.value}"/>\n'
            "    </testcase>"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<testsuite name="webscope" tests="{summary["total"]}" failures="{summary["total"]}">\n'
        + "\n".join(cases)
        + "\n</testsuite>\n"
    )


def render_html(result: ScanResult) -> str:
    """Автономный HTML-отчёт (один файл, без внешних зависимостей)."""
    summary = result.summary
    archetype = result.archetype or {}
    stack = ", ".join(filter(None, [archetype.get("framework"), archetype.get("cms"), archetype.get("ui_kit")]))

    rows = []
    for index, finding in enumerate(result.findings, start=1):
        selector = f"<code>{html_lib.escape(finding.selector)}</code>" if finding.selector else ""
        snippet = f"<pre>{html_lib.escape(finding.snippet)}</pre>" if finding.snippet else ""
        help_link = f'<a href="{html_lib.escape(finding.help_url)}">документация</a>' if finding.help_url else ""
        rows.append(
            f"""<tr class="sev-{finding.severity.value}">
  <td>{index}</td>
  <td><span class="badge {finding.severity.value}">{SEVERITY_LABEL[finding.severity]}</span></td>
  <td><strong>{html_lib.escape(finding.title)}</strong><br><small>{html_lib.escape(finding.rule)}</small></td>
  <td>{html_lib.escape(finding.message)}</td>
  <td>{selector}{snippet}</td>
  <td>{help_link}</td>
</tr>"""
        )

    table = "\n".join(rows) or '<tr><td colspan="6">Проблем не найдено</td></tr>'

    return f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>webscope — {html_lib.escape(result.url)}</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font: 15px/1.5 system-ui, sans-serif; margin: 32px; max-width: 1100px; }}
  h1 {{ font-size: 20px; margin-bottom: 4px; }}
  .meta {{ color: #666; font-size: 13px; margin-bottom: 20px; }}
  .cards {{ display: flex; gap: 10px; margin-bottom: 24px; flex-wrap: wrap; }}
  .card {{ border: 1px solid #8884; border-radius: 8px; padding: 10px 14px; min-width: 96px; }}
  .card b {{ display: block; font-size: 22px; }}
  table {{ border-collapse: collapse; width: 100%; }}
  th, td {{ border-bottom: 1px solid #8883; padding: 8px 10px; text-align: left; vertical-align: top; font-size: 14px; }}
  th {{ font-size: 12px; text-transform: uppercase; letter-spacing: .04em; color: #666; }}
  code {{ font-size: 12px; word-break: break-all; }}
  pre {{ font-size: 12px; background: #8881; padding: 6px 8px; border-radius: 6px; overflow-x: auto; }}
  .badge {{ font-size: 11px; font-weight: 700; padding: 2px 7px; border-radius: 999px; color: #fff; }}
  .badge.critical {{ background: #b3261e; }} .badge.serious {{ background: #d97706; }}
  .badge.moderate {{ background: #2563eb; }} .badge.minor {{ background: #6b7280; }}
  .note {{ margin-top: 28px; font-size: 12px; color: #777; }}
</style>
</head>
<body>
<h1>webscope — отчёт по {html_lib.escape(result.final_url or result.url)}</h1>
<div class="meta">
  title: {html_lib.escape(result.title or "")} · стек: {html_lib.escape(stack or "не определён")} ·
  длительность: {result.duration_ms} мс · {result.generated_at}
</div>
<div class="cards">
  <div class="card"><b>{summary["critical"]}</b>critical</div>
  <div class="card"><b>{summary["serious"]}</b>serious</div>
  <div class="card"><b>{summary["moderate"]}</b>moderate</div>
  <div class="card"><b>{summary["minor"]}</b>minor</div>
</div>
<table>
<tr><th>#</th><th>severity</th><th>правило</th><th>почему это проблема</th><th>где</th><th>доки</th></tr>
{table}
</table>
<p class="note">Отчёт сформирован автоматически. Автоматизированные проверки покрывают лишь часть критериев
WCAG и не являются юридическим заключением о соответствии.</p>
</body>
</html>"""


def build_fix_prompt(result: ScanResult, rules: list[str] | None = None) -> str:
    """Собирает ТЗ для coding-агента из находок.

    Это основная точка ценности: находки превращаются в задачу, которую агент
    может выполнить и проверить повторным сканом.
    """
    selected = [f for f in result.findings if not rules or f.rule in rules]
    if not selected:
        return f"По URL {result.final_url or result.url} находок webscope нет — исправлять нечего."

    lines = [
        f"Исправь следующие находки webscope на {result.final_url or result.url}.",
        "",
        "Для каждой находки:",
        "1. Найди элемент по CSS-селектору (приоритет — data-testid, затем устойчивые селекторы).",
        "2. Исправь разметку/стили так, чтобы выполнялся критерий приёмки.",
        "3. Не меняй поведение и вёрстку в сторонах, не относящихся к находке.",
        "4. После правок прогони `webscope scan <url> --format json` и убедись, что находка исчезла,",
        "   а новых не появилось.",
        "",
        f"Найдено: {len(selected)}",
        "",
    ]

    for index, finding in enumerate(selected, start=1):
        lines.append(f"[{index}] {finding.rule} ({finding.severity.value}) — {finding.title}")
        lines.append(f"    где:    {finding.url}" + (f" → {finding.selector}" if finding.selector else ""))
        if finding.snippet:
            lines.append(f"    html:   {finding.snippet}")
        if finding.message:
            lines.append(f"    почему: {finding.message}")
        lines.append(f"    приёмка: {acceptance_for(finding)}")
        if finding.help_url:
            lines.append(f"    доки:   {finding.help_url}")
        lines.append("")

    return "\n".join(lines)
