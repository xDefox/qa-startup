"""Формирование отчётов: текст, JSON, HTML, SARIF, JUnit и fix-prompt для агента."""

from __future__ import annotations

import html as html_lib
import json
from typing import TYPE_CHECKING, Any

from .models import Finding, ScanResult, Severity
from .pages import page_notes
from .scoring import is_false_positive

if TYPE_CHECKING:
    from .history import DiffReport

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
    "content/frame-title": "У iframe есть непустой title.",
    "content/empty-link-name": "У ссылки есть осмысленный текст или aria-label.",
    "content/empty-button-name": "У кнопки есть текст или aria-label.",
    "content/duplicate-id": "id на странице уникальны.",
    "content/duplicate-title": "Каждая страница шаблона имеет уникальный <title>.",
    "content/duplicate-description": "Каждая страница шаблона имеет уникальный meta description.",
    "content/missing-og-title": 'В <head> есть <meta property="og:title" content="...">.',
    "content/missing-og-image": 'В <head> есть <meta property="og:image" content="https://...png"> с обложкой 1200×630.',
    "forms/control-without-label": "У поля есть <label for> (или aria-label/aria-labelledby).",
    "forms/placeholder-as-label": "У поля есть постоянная подпись <label>, а не только placeholder.",
    "forms/control-without-name": "У поля есть атрибут name, значение отправляется в форму.",
    "forms/email-without-autocomplete": 'У email-поля есть autocomplete="email".',
    "forms/submit-without-accessible-name": "У кнопки есть текст или aria-label.",
    "forms/novalidate": "У формы нет novalidate либо есть своя валидация с видимыми сообщениями об ошибках.",
    "forms/email-wrong-type": 'Поле email имеет type="email".',
    "forms/tel-missing-inputmode": 'У поля телефона задан inputmode="tel".',
    "interaction/button-blocked": "Центр кнопки/ссылки кликабелен: elementFromPoint возвращает сам элемент или его потомка.",
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
    if summary.get("external"):
        lines.append(f"в виджетах: {summary['external']} (чужие домены — не дефект сайта)")
    fp_count = sum(1 for f in result.findings if is_false_positive(f))
    if fp_count:
        lines.append(f"ложные срабатывания (FP): {fp_count} — исключены из оценки")

    # Фильтруем FP для отображения
    display_findings = [f for f in result.findings if not is_false_positive(f)]
    if not display_findings:
        lines.append("")
        lines.append("Проблем не найдено.")
        return "\n".join(lines)

    lines.append("")
    for index, finding in enumerate(display_findings, start=1):
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
    # Исключаем FP из JSON-отчёта
    filtered = ScanResult(
        url=result.url,
        final_url=result.final_url,
        title=result.title,
        archetype=result.archetype,
        duration_ms=result.duration_ms,
        pages_scanned=result.pages_scanned,
        findings=[f for f in result.findings if not is_false_positive(f)],
        schema_version=result.schema_version,
        generated_at=result.generated_at,
    )
    return json.dumps(filtered.to_dict(), ensure_ascii=False, indent=2)


def render_sarif(result: ScanResult) -> str:
    """SARIF — формат, который понимают GitHub Code Scanning и IDE."""
    rules: dict[str, dict[str, Any]] = {}
    results: list[dict[str, Any]] = []

    for finding in result.findings:
        if is_false_positive(finding):
            continue
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
                # GitHub Code Scanning склеивает результаты между прогонами по
                # отпечатку: без него каждая проверка создаёт новые алерты,
                # и вместо «третья проблема за неделю» получается «300 алертов».
                "partialFingerprints": {"webscopeFinding/v1": finding.fingerprint},
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
    # Фильтруем FP
    display_findings = [f for f in result.findings if not is_false_positive(f)]
    fp_count = len(result.findings) - len(display_findings)
    
    summary = result.summary
    archetype = result.archetype or {}
    stack = ", ".join(filter(None, [archetype.get("framework"), archetype.get("cms"), archetype.get("ui_kit")]))

    rows = []
    for index, finding in enumerate(display_findings, start=1):
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
  {f'<div class="card" style="border-color: #888;"><b>{fp_count}</b>FP (исключены)</div>' if fp_count else ''}
</div>
<table>
<tr><th>#</th><th>severity</th><th>правило</th><th>почему это проблема</th><th>где</th><th>доки</th></tr>
{table}
</table>
<p class="note">Отчёт сформирован автоматически. Автоматизированные проверки покрывают лишь часть критериев
WCAG и не являются юридическим заключением о соответствии.</p>
</body>
</html>"""


def render_pdf(result: ScanResult) -> bytes:
    """PDF-отчёт — автономный файл (fpdf2), можно скачать или открыть в браузере."""
    from fpdf import FPDF

    from .scoring import (
        compute_score,
        group_by_rule,
        is_false_positive,
        is_site_defect,
        plain_impact,
        score_label,
        top_actions,
    )

    score = compute_score(result.findings, result.pages_scanned)
    own = [finding for finding in result.findings if is_site_defect(finding) and not is_false_positive(finding)]
    fu = result.final_url or result.url

    pdf = FPDF()
    # Add Unicode font for Cyrillic support
    pdf.add_font("LiberationSans", "", "/usr/share/fonts/liberation/LiberationSans-Regular.ttf", uni=True)
    pdf.add_font("LiberationSans", "B", "/usr/share/fonts/liberation/LiberationSans-Bold.ttf", uni=True)
    pdf.add_font("LiberationSans", "I", "/usr/share/fonts/liberation/LiberationSans-Italic.ttf", uni=True)
    pdf.add_font("LiberationSans", "BI", "/usr/share/fonts/liberation/LiberationSans-BoldItalic.ttf", uni=True)
    pdf.add_page()
    pdf.set_font("LiberationSans", size=11)

    # Color constants
    COLOR_PRIMARY = (37, 99, 235)      # Blue
    COLOR_SUCCESS = (34, 197, 94)      # Green
    COLOR_WARNING = (234, 179, 8)      # Yellow
    COLOR_DANGER = (239, 68, 68)       # Red
    COLOR_GRAY = (107, 114, 128)       # Gray
    COLOR_LIGHT_BG = (243, 244, 246)   # Light gray background
    COLOR_WHITE = (255, 255, 255)

    def section_title(title: str):
        pdf.set_font("LiberationSans", "B", 14)
        pdf.set_text_color(*COLOR_PRIMARY)
        pdf.cell(0, 10, title, ln=True)
        pdf.set_draw_color(*COLOR_PRIMARY)
        pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
        pdf.ln(4)
        pdf.set_text_color(0, 0, 0)
        pdf.set_font("LiberationSans", size=11)

    def subsection_title(title: str):
        pdf.set_font("LiberationSans", "B", 12)
        pdf.set_text_color(*COLOR_GRAY)
        pdf.cell(0, 8, title, ln=True)
        pdf.ln(2)
        pdf.set_text_color(0, 0, 0)
        pdf.set_font("LiberationSans", size=11)

    def body_text(text: str):
        pdf.multi_cell(0, 6, text)
        pdf.ln(2)

    def severity_badge(severity: str) -> tuple:
        """Return (bg_color, text_color) for severity."""
        if severity == "critical":
            return COLOR_DANGER, COLOR_WHITE
        elif severity == "serious":
            return (249, 115, 22), COLOR_WHITE  # Orange
        elif severity == "moderate":
            return COLOR_WARNING, (0, 0, 0)
        else:
            return COLOR_GRAY, COLOR_WHITE

    # ========== HEADER ==========
    pdf.set_fill_color(*COLOR_PRIMARY)
    pdf.rect(0, 0, pdf.w, 45, "F")
    pdf.set_y(8)
    pdf.set_font("LiberationSans", "B", 22)
    pdf.set_text_color(*COLOR_WHITE)
    pdf.cell(0, 12, "webscope", ln=True, align="C")
    pdf.set_font("LiberationSans", size=11)
    pdf.cell(0, 8, "Отчёт по сканированию качества сайта", ln=True, align="C")
    pdf.ln(6)
    pdf.set_text_color(0, 0, 0)

    # ========== SITE INFO ==========
    section_title("Информация о сайте")
    pdf.set_font("LiberationSans", "B", 11)
    pdf.cell(25, 7, "URL:")
    pdf.set_font("LiberationSans", size=11)
    pdf.cell(0, 7, fu, ln=True)
    if result.title:
        pdf.set_font("LiberationSans", "B", 11)
        pdf.cell(25, 7, "Название:")
        pdf.set_font("LiberationSans", size=11)
        pdf.cell(0, 7, result.title, ln=True)
    pdf.set_font("LiberationSans", "B", 11)
    pdf.cell(25, 7, "Дата:")
    pdf.set_font("LiberationSans", size=11)
    from datetime import datetime, UTC
    pdf.cell(0, 7, datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"), ln=True)
    pdf.ln(3)

    # ========== SCORE SUMMARY ==========
    section_title("Сводка результатов")
    
    # Score box
    pdf.set_fill_color(*COLOR_LIGHT_BG)
    pdf.rect(pdf.l_margin, pdf.get_y(), pdf.w - pdf.l_margin - pdf.r_margin, 28, "F")
    pdf.set_xy(pdf.l_margin + 5, pdf.get_y() + 3)
    
    # Score circle simulation
    if score >= 80:
        score_color = COLOR_SUCCESS
    elif score >= 60:
        score_color = COLOR_WARNING
    elif score >= 40:
        score_color = (249, 115, 22)
    else:
        score_color = COLOR_DANGER
    
    pdf.set_font("LiberationSans", "B", 10)
    pdf.set_text_color(*COLOR_GRAY)
    pdf.cell(40, 7, "ОЦЕНКА САЙТА", ln=True)
    pdf.set_x(pdf.l_margin + 5)
    pdf.set_font("LiberationSans", "B", 36)
    pdf.set_text_color(*score_color)
    pdf.cell(40, 18, f"{score}/100", ln=True)
    pdf.set_x(pdf.l_margin + 5)
    pdf.set_font("LiberationSans", size=10)
    pdf.set_text_color(*COLOR_GRAY)
    pdf.cell(0, 6, score_label(score), ln=True)
    pdf.ln(6)
    pdf.set_text_color(0, 0, 0)

    # Metrics row
    fp_count = sum(1 for f in result.findings if is_false_positive(f))
    critical_count = sum(1 for f in own if f.severity.value == "critical")
    serious_count = sum(1 for f in own if f.severity.value == "serious")
    moderate_count = sum(1 for f in own if f.severity.value == "moderate")
    minor_count = sum(1 for f in own if f.severity.value == "minor")

    col_w = (pdf.w - pdf.l_margin - pdf.r_margin) / 5
    metrics = [
        ("Страниц", str(result.pages_scanned), COLOR_PRIMARY),
        ("Всего проблем", str(len(own)), COLOR_GRAY),
        ("Критично", str(critical_count), COLOR_DANGER),
        ("Существенно", str(serious_count), (249, 115, 22)),
        ("Желательно", str(moderate_count), COLOR_WARNING),
    ]
    
    for i, (label, value, color) in enumerate(metrics):
        x = pdf.l_margin + i * col_w
        pdf.set_xy(x, pdf.get_y())
        pdf.set_fill_color(*COLOR_LIGHT_BG)
        pdf.rect(x, pdf.get_y(), col_w, 16, "F")
        pdf.set_xy(x, pdf.get_y() + 2)
        pdf.set_font("LiberationSans", size=8)
        pdf.set_text_color(*COLOR_GRAY)
        pdf.cell(col_w, 5, label, align="C")
        pdf.set_xy(x, pdf.get_y() + 5)
        pdf.set_font("LiberationSans", "B", 14)
        pdf.set_text_color(*color)
        pdf.cell(col_w, 8, value, align="C")
    pdf.ln(18)
    pdf.set_text_color(0, 0, 0)

    if fp_count:
        pdf.set_font("LiberationSans", "I", 10)
        pdf.set_text_color(*COLOR_GRAY)
        pdf.cell(0, 7, f"Ложных срабатываний (FP): {fp_count} — исключены из оценки", ln=True)
        pdf.set_text_color(0, 0, 0)
        pdf.ln(3)

    # ========== TOP ACTIONS ==========
    if own:
        actions = top_actions(own, limit=3)
        if actions:
            section_title("Приоритетные действия (Топ-3)")
            for index, finding in enumerate(actions, start=1):
                meaning, fix = plain_impact(finding)
                
                # Action card background
                y_start = pdf.get_y()
                pdf.set_fill_color(*COLOR_LIGHT_BG)
                pdf.rect(pdf.l_margin, y_start, pdf.w - pdf.l_margin - pdf.r_margin, 28, "F")
                pdf.set_xy(pdf.l_margin + 3, y_start + 2)
                
                # Number badge
                pdf.set_font("LiberationSans", "B", 10)
                pdf.set_fill_color(*COLOR_PRIMARY)
                pdf.set_text_color(*COLOR_WHITE)
                pdf.cell(8, 6, f" {index} ", fill=True, align="C")
                pdf.set_text_color(0, 0, 0)
                pdf.set_font("LiberationSans", "B", 11)
                pdf.cell(0, 6, f" {meaning}", ln=True)
                
                pdf.set_x(pdf.l_margin + 12)
                pdf.set_font("LiberationSans", size=10)
                pdf.set_text_color(*COLOR_GRAY)
                pdf.multi_cell(pdf.w - pdf.l_margin - pdf.r_margin - 12, 5, f"Что сделать: {fix}")
                
                if finding.url:
                    pdf.set_x(pdf.l_margin + 12)
                    pdf.set_font("LiberationSans", "I", 9)
                    pdf.cell(0, 5, f"Страница: {finding.url}", ln=True)
                pdf.ln(4)
                pdf.set_text_color(0, 0, 0)
            pdf.ln(3)

        # ========== FINDINGS TABLE BY SEVERITY ==========
        section_title("Детальный список проблем")

        # Group by severity
        from collections import defaultdict
        by_severity = defaultdict(list)
        for f in own:
            by_severity[f.severity.value].append(f)

        severity_order = ["critical", "serious", "moderate", "minor"]
        severity_labels = {
            "critical": "Критичные",
            "serious": "Существенные",
            "moderate": "Желательные",
            "minor": "Мелкие",
        }

        for sev in severity_order:
            findings_sev = by_severity.get(sev, [])
            if not findings_sev:
                continue

            subsection_title(f"{severity_labels[sev]} ({len(findings_sev)})")

            # Table header
            pdf.set_font("LiberationSans", "B", 9)
            pdf.set_fill_color(*COLOR_LIGHT_BG)
            col_rule = (pdf.w - pdf.l_margin - pdf.r_margin) * 0.35
            col_page = (pdf.w - pdf.l_margin - pdf.r_margin) * 0.25
            col_desc = (pdf.w - pdf.l_margin - pdf.r_margin) * 0.40
            
            pdf.cell(col_rule, 7, "Правило", border=1, fill=True, align="C")
            pdf.cell(col_page, 7, "Страница", border=1, fill=True, align="C")
            pdf.cell(col_desc, 7, "Описание", border=1, fill=True, align="C")
            pdf.ln()

            # Table rows
            pdf.set_font("LiberationSans", size=8)
            for f in findings_sev[:15]:  # Limit to 15 per severity
                rule_short = f.rule
                if len(rule_short) > 28:
                    rule_short = rule_short[:25] + "..."
                page_url = f.url or "-"
                if len(page_url) > 25:
                    page_url = page_url[:22] + "..."
                desc = f.message
                if len(desc) > 45:
                    desc = desc[:42] + "..."

                bg_color = COLOR_LIGHT_BG if findings_sev.index(f) % 2 == 0 else COLOR_WHITE
                pdf.set_fill_color(*bg_color)
                pdf.cell(col_rule, 6, rule_short, border=1, fill=True)
                pdf.cell(col_page, 6, page_url, border=1, fill=True)
                pdf.cell(col_desc, 6, desc, border=1, fill=True)
                pdf.ln()

            if len(findings_sev) > 15:
                pdf.set_font("LiberationSans", "I", 8)
                pdf.set_text_color(*COLOR_GRAY)
                pdf.cell(0, 5, f"  ... и ещё {len(findings_sev) - 15} проблем этой категории", ln=True)
                pdf.set_text_color(0, 0, 0)
            pdf.ln(4)

        # ========== BLOCKING CLICKS ==========
        blockers = group_by_rule([f for f in own if f.rule == "interaction/button-blocked"])
        if blockers:
            section_title("Блокирующие клики — нельзя нажать кнопку/ссылку (критично)")
            for group in blockers:
                meaning, fix = group["meaning"], group["fix"]
                body_text(f"• {meaning}")
                if group["examples"]:
                    body_text(f"  Где: {group['examples'][0]}")
                body_text(f"  Что сделать: {fix}")
            pdf.ln(3)

    else:
        section_title("Результат")
        pdf.set_font("LiberationSans", "B", 14)
        pdf.set_text_color(*COLOR_SUCCESS)
        pdf.cell(0, 10, "Проблем не найдено — отличный результат!", ln=True, align="C")
        pdf.set_text_color(0, 0, 0)
        pdf.ln(5)

    # ========== FOOTER ==========
    pdf.ln(10)
    pdf.set_draw_color(*COLOR_GRAY)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(3)
    pdf.set_font("LiberationSans", "I", 9)
    pdf.set_text_color(*COLOR_GRAY)
    pdf.multi_cell(0, 5, "Отчёт сформирован автоматически системой webscope. Автоматизированные проверки покрывают лишь часть критериев WCAG — для полного аудита доступности рекомендуется ручная проверка специалистом.")
    pdf.set_text_color(0, 0, 0)

    return bytes(pdf.output())


def render_plain(result: ScanResult) -> str:
    """Отчёт для владельца сайта: без терминов, с баллом и планом действий."""
    from .scoring import (
        compute_score,
        group_by_rule,
        is_false_positive,
        is_site_defect,
        plain_impact,
        score_label,
        top_actions,
    )

    score = compute_score(result.findings, result.pages_scanned)
    own = [finding for finding in result.findings if is_site_defect(finding) and not is_false_positive(finding)]
    fp_count = sum(1 for f in result.findings if is_false_positive(f))
    lines: list[str] = []

    fu = result.final_url or result.url
    lines.append(f"Проверка сайта: {fu}")
    if result.title:
        lines.append(f"Название: {result.title}")
    lines.append(f"Проверено страниц: {result.pages_scanned}")
    lines.append(f"Оценка: {score}/100 — {score_label(score)}")
    if fp_count:
        lines.append(f"Ложных срабатываний (FP): {fp_count} — исключены из оценки")
    for note in page_notes(result.url, result.final_url):
        lines.append(f"Примечание: {note}")
    lines.append("")

    if not own:
        lines.append("Серьёзных проблем не найдено. Сайт в порядке.")
        return "\n".join(lines)

    actions = top_actions(own, limit=3)
    if actions:
        lines.append("ЧТО СДЕЛАТЬ В ПЕРВУЮ ОЧЕРЕДЬ")
        for index, finding in enumerate(actions, start=1):
            meaning, fix = plain_impact(finding)
            lines.append(f"  {index}. {meaning}")
            lines.append(f"     Что сделать: {fix}")
            if finding.url:
                lines.append(f"     Страница: {finding.url}")
        lines.append("")

    blockers = group_by_rule([f for f in own if f.rule == "interaction/button-blocked"])
    if blockers:
        lines.append("БЛОКИРУЕТ КЛИКИ — нельзя нажать кнопку/ссылку (критично)")
        for group in blockers:
            meaning, fix = group["meaning"], group["fix"]
            rep = group.get("representative")
            lines.append(f"  • {meaning}")
            if rep and getattr(rep, "selector", None):
                lines.append(f"    Селектор: {rep.selector}")
            if group["pages_count"] > 1 or group["count"] > 1:
                lines.append(f"    Затронуто: {group['pages_count']} стр., элементов: {group['count']}")
                if group["examples"]:
                    if len(group["examples"]) == 1:
                        location = group["examples"][0]
                    else:
                        location = ", ".join(group["examples"])
                        if len(group["pages"]) > len(group["examples"]):
                            location += f" и ещё {len(group['pages']) - len(group['examples'])} стр."
                    lines.append(f"    Где: {location}")
            elif group["count"] == 1 and group["examples"]:
                lines.append(f"    Страница: {group['examples'][0]}")
            if (
                rep
                and getattr(rep, "url", None)
                and (group["pages_count"] <= 1 or rep.url not in (group.get("examples") or []))
            ):
                lines.append(f"    URL: {rep.url}")
            lines.append(f"    Что сделать: {fix}")
            if rep and getattr(rep, "snippet", None):
                lines.append(f"    Фрагмент: {rep.snippet}")
        lines.append("")

    groups = (
        ("КРИТИЧНО — сайт работает неправильно", "critical"),
        ("СУЩЕСТВЕННО — часть клиентов теряется", "serious"),
        ("РЕКОМЕНДАЦИИ ПО УЛУЧШЕНИЮ", "moderate"),
        ("МЕЛОЧИ — на ваше усмотрение", "minor"),
    )
    for title, key in groups:
        items = group_by_rule(
            [
                finding
                for finding in own
                if finding.severity.value == key and finding.rule != "interaction/button-blocked"
            ]
        )
        if not items:
            continue
        lines.append(f"{title} ({len(items)} правил)")
        for group in items:
            meaning, fix = group["meaning"], group["fix"]
            lines.append(f"  • {meaning}")
            rep = group.get("representative")
            if rep and getattr(rep, "selector", None):
                lines.append(f"    Селектор: {rep.selector}")
            if group["pages_count"] > 1 or group["count"] > 1:
                lines.append(f"    Затронуто: {group['pages_count']} стр., элементов: {group['count']}")
                if group["examples"]:
                    if len(group["examples"]) == 1:
                        location = group["examples"][0]
                    else:
                        location = ", ".join(group["examples"])
                        if len(group["pages"]) > len(group["examples"]):
                            location += f" и ещё {len(group['pages']) - len(group['examples'])} стр."
                    lines.append(f"    Где: {location}")
            elif group["count"] == 1 and group["examples"]:
                lines.append(f"    Страница: {group['examples'][0]}")
            if (
                rep
                and getattr(rep, "url", None)
                and (group["pages_count"] <= 1 or rep.url not in (group.get("examples") or []))
            ):
                lines.append(f"    URL: {rep.url}")
            lines.append(f"    Что сделать: {fix}")
            if rep and getattr(rep, "snippet", None):
                lines.append(f"    Фрагмент: {rep.snippet}")
            if rep and getattr(rep, "rule", "") in ("console/error", "console/failed-request"):
                if getattr(rep, "message", None):
                    lines.append(f"    Детали: {rep.message}")
                if rep.details:
                    loc = rep.details.get("location") or rep.details.get("location_url") or rep.details.get("resource")
                    if loc and loc not in str(rep.message):
                        lines.append(f"    Источник/ресурс: {loc}")
        lines.append("")

    external_groups = group_by_rule([f for f in result.findings if not is_site_defect(f)])
    if external_groups:
        lines.append(f"ЗАМЕЧАНИЯ СКАНИРОВАНИЯ, НЕ ДЕФЕКТЫ САЙТА ({len(external_groups)} правил)")
        total = sum(group["count"] for group in external_groups)
        lines.append(f"  Это ошибки и блокировки на чужих доменах (счётчики, карты, реклама, SDK) — {total} шт.")
        lines.append("  Исправлять на своём сайте нечего; на балл они не влияют.")
        for group in external_groups:
            rep = group.get("representative")
            host = ""
            details = getattr(rep, "details", None) or {}
            source = details.get("location_url") or details.get("resource") or details.get("location") or ""
            if source:
                host = source.split("//", 1)[-1].split("/", 1)[0]
            lines.append(f"  • {group['title']}: {group['count']}" + (f" (например, {host})" if host else ""))
        lines.append("")

    fp_groups = group_by_rule([f for f in result.findings if is_site_defect(f) and is_false_positive(f)])
    if fp_groups:
        lines.append(f"ЛОЖНЫЕ СРАБАТЫВАНИЯ (FP) — ИСКЛЮЧЕНЫ ИЗ ОЦЕНКИ И ПЛАНА ДЕЙСТВИЙ ({len(fp_groups)} правил)")
        total = sum(group["count"] for group in fp_groups)
        lines.append(f"  Эти находки помечены как ложные срабатывания — {total} шт.")
        lines.append("  Они не влияют на оценку и не требуют исправления.")
        for group in fp_groups:
            rep = group.get("representative")
            lines.append(f"  • {group['title']}: {group['count']}")
        lines.append("")

    lines.append(
        "Проверка автоматическая: она находит типовые проблемы доступности, скорости и "
        "работоспособности, но не заменяет проверку человеком."
    )
    return "\n".join(lines)


def render_diff(diff: DiffReport) -> str:
    """Человекочитаемый разбор изменений между двумя прогонами."""
    delta = diff.score_after - diff.score_before
    arrow = "+" if delta > 0 else ""
    lines = [
        f"Сравнение: {diff.old_at} → {diff.new_at}",
        f"Оценка: {diff.score_before} → {diff.score_after} ({arrow}{delta})",
        (
            f"Новых проблем: {len(diff.new_findings)} · исправлено: {len(diff.fixed_findings)} · "
            f"изменилось: {len(diff.changed_findings)}"
        ),
        "",
    ]

    if diff.new_findings:
        lines.append("НОВЫЕ ПРОБЛЕМЫ")
        for entry in diff.new_findings:
            lines.append(f"  • [{entry.severity_after}] {entry.title} — {entry.url}")
        lines.append("")

    if diff.fixed_findings:
        lines.append("ИСПРАВЛЕНО")
        for entry in diff.fixed_findings:
            lines.append(f"  • {entry.title} — {entry.url}")
        lines.append("")

    if diff.changed_findings:
        lines.append("ИЗМЕНИЛОСЬ")
        for entry in diff.changed_findings:
            lines.append(f"  • {entry.title}: {entry.severity_before} → {entry.severity_after} — {entry.url}")
        lines.append("")

    if not (diff.new_findings or diff.fixed_findings or diff.changed_findings):
        lines.append("Изменений нет — сайт в том же состоянии.")

    return "\n".join(lines)


def render_trend(points: list[dict]) -> str:
    """Таблица динамики по истории прогонов."""
    if not points:
        return "История пуста — сделайте первый прогон."
    lines = ["дата                оценка  всего  crit  serious  moderate  minor  страниц"]
    for point in points:
        lines.append(
            "{taken_at:<20} {score:>5}  {total:>5}  {critical:>4}  {serious:>6}  {moderate:>8}  {minor:>5}  {pages:>6}".format(
                taken_at=point.get("taken_at", "")[:19],
                score=point.get("score", 0),
                total=point.get("total", 0),
                critical=point.get("critical", 0),
                serious=point.get("serious", 0),
                moderate=point.get("moderate", 0),
                minor=point.get("minor", 0),
                pages=point.get("pages_scanned", 0),
            )
        )
    return "\n".join(lines)


def build_fix_prompt(result: ScanResult, rules: list[str] | None = None) -> str:
    """Собирает ТЗ для coding-агента из находок.

    Это основная точка ценности: находки превращаются в задачу, которую агент
    может выполнить и проверить повторным сканом.
    
    Ложные срабатывания (FP) исключаются — агент не должен их чинить.
    """
    from .scoring import is_false_positive
    
    selected = [f for f in result.findings if not is_false_positive(f) and (not rules or f.rule in rules)]
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
