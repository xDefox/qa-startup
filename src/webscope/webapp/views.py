"""Данные для страницы отчёта: группы находок, блокеры, план действий, дифф.

Функции здесь ничего не знают про HTTP: на вход строка прогона из хранилища,
на выход словари для шаблона. Поэтому их можно проверять без веб-приложения.
"""

from __future__ import annotations

from ..models import ScanResult, Severity
from ..pages import page_notes
from ..scoring import group_by_rule, is_false_positive, is_site_defect, plain_impact, score_label, top_actions
from .storage import Run, Storage

BLOCKER_RULE = "interaction/button-blocked"

SEVERITY_GROUPS = (
    (Severity.CRITICAL, "Критично — сайт работает неправильно", "critical"),
    (Severity.SERIOUS, "Существенно — часть клиентов теряется", "serious"),
    (Severity.MODERATE, "Желательно — стоит поправить", "moderate"),
    (Severity.MINOR, "Мелочи — на ваше усмотрение", "minor"),
)

# Третья категория находок: ошибки на чужих доменах (счётчики, карты, реклама).
# Показываем их отдельной группой, чтобы в таблице были видны все находки,
# но не путались с дефектами сайта.
EXTERNAL_TITLE = "Замечания сканирования — не дефекты сайта (чужие виджеты)"

FP_TITLE = "Ложные срабатывания (FP) — исключены из оценки и плана действий"

SCHEDULE_LABELS = {
    "off": "без автоматических проверок",
    "daily": "каждый день",
    "weekly": "каждую неделю",
    "monthly": "каждый месяц",
}

SEVERITY_LABELS = {
    "critical": "критично",
    "serious": "существенно",
    "moderate": "желательно",
    "minor": "мелочь",
    "external": "виджет",
}


def problem_view(group: dict) -> dict:
    """Одна проблема для шаблона: что, где и как проверить."""
    rep = group.get("representative")
    details = getattr(rep, "details", None) or {}
    source = details.get("location") or details.get("location_url") or details.get("resource") or ""
    if not source:
        checker = getattr(rep, "source", "") or ""
        # внутренние пометки вида «webscope.forms» пользователю не интересны
        source = "" if checker.startswith("webscope") else checker
    severity = getattr(rep, "severity", None)
    return {
        "severity": getattr(severity, "value", str(severity or "")),
        "severity_label": SEVERITY_LABELS.get(getattr(severity, "value", ""), getattr(severity, "value", "")),
        "meaning": group["meaning"],
        "fix": group["fix"],
        "url": ", ".join(group["examples"]) if group["examples"] else "",
        "pages_count": group["pages_count"],
        "count": group["count"],
        "rule": group["rule"],
        "selector": getattr(rep, "selector", None) or "",
        "snippet": getattr(rep, "snippet", None) or "",
        "message": getattr(rep, "message", None) or "",
        "source": source,
        "help_url": getattr(rep, "help_url", None) or "",
        "details": details,  # <-- added for FP button and template access
    }


def build_report_view(storage: Storage, run: Run) -> dict:
    """Готовит данные для страницы отчёта: группы, план действий, дифф."""
    findings = storage.findings_as_models(run.id)

    blocker_groups = group_by_rule([f for f in findings if f.rule == BLOCKER_RULE and not is_false_positive(f)])
    blockers = [problem_view(group) for group in blocker_groups]

    # Находки делятся на ЧЕТЫРЕ категории:
    # 1) проблемы самого сайта (блокеры кликов — отдельной карточкой),
    # 2) мелочи сайта,
    # 3) замечания сканирования — ошибки на чужих доменах,
    # 4) ложные срабатывания (FP) — исключены из скора и плана действий.
    own = [finding for finding in findings if is_site_defect(finding) and not is_false_positive(finding)]
    fp_findings = [finding for finding in findings if is_site_defect(finding) and is_false_positive(finding)]
    external = [finding for finding in findings if not is_site_defect(finding)]
    groups = []
    for severity, title, key in SEVERITY_GROUPS:
        items = group_by_rule(
            [finding for finding in own if finding.severity == severity and finding.rule != BLOCKER_RULE]
        )
        if not items:
            continue
        groups.append(
            {
                "title": title,
                "key": key,
                "count": len(items),
                "problems": [problem_view(group) for group in items],
            }
        )
    external_items = group_by_rule(external)
    if external_items:
        groups.append(
            {
                "title": EXTERNAL_TITLE,
                "key": "external",
                "count": len(external_items),
                "problems": [problem_view(group) for group in external_items],
            }
        )
    fp_items = group_by_rule(fp_findings)
    if fp_items:
        groups.append(
            {
                "title": FP_TITLE,
                "key": "fp",
                "count": len(fp_items),
                "problems": [problem_view(group) for group in fp_items],
            }
        )

    actions = [
        {
            "meaning": plain_impact(finding)[0],
            "fix": plain_impact(finding)[1],
            "url": finding.url,
            "selector": finding.selector or "",
        }
        for finding in top_actions(own, limit=3)
    ]

    diff = storage.diff_with_previous(run)
    diff_view = None
    if diff is not None:
        diff_view = {
            "delta": diff.score_after - diff.score_before,
            "score_before": diff.score_before,
            "score_after": diff.score_after,
            "new": [
                {"title": entry.title, "url": entry.url, "severity": entry.severity_after}
                for entry in diff.new_findings[:10]
            ],
            "fixed": [{"title": entry.title, "url": entry.url} for entry in diff.fixed_findings[:10]],
            "new_count": len(diff.new_findings),
            "fixed_count": len(diff.fixed_findings),
        }

    score = run.score if run.score is not None else 100
    return {
        "run": run,
        "score": score,
        "score_label": score_label(score),
        "blockers": blockers,
        "groups": groups,
        "actions": actions,
        "diff": diff_view,
        "total": len(own),
        "external_total": len(external),
        "has_external": bool(external),
        "notes": page_notes(run.raw.get("url"), run.raw.get("final_url")),
    }


def result_from_run(storage: Storage, run: Run) -> ScanResult:
    """Собирает ScanResult из сохранённого прогона."""
    result = ScanResult(
        url=run.raw.get("url", ""),
        final_url=run.raw.get("final_url"),
        title=run.raw.get("title"),
        archetype=run.raw.get("archetype", {}),
        duration_ms=run.duration_ms,
        pages_scanned=run.pages_scanned,
    )
    result.findings = storage.findings_as_models(run.id)
    return result


__all__ = [
    "BLOCKER_RULE",
    "EXTERNAL_TITLE",
    "SCHEDULE_LABELS",
    "SEVERITY_GROUPS",
    "SEVERITY_LABELS",
    "build_report_view",
    "problem_view",
    "result_from_run",
]
