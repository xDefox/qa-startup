"""Формы: подписи, имена полей, доступность элементов управления.

Типовые формы (логин, поиск, контактная форма, чекаут) устроены одинаково на всех
сайтах — именно на этом держится предположение «у сайтов общая структура».
"""

from __future__ import annotations

from ...context import ScanContext
from ...models import Finding, Severity

COLLECT = r"""
() => {
  const u = window.__webscopeUtils;
  const skippedTypes = ['hidden', 'submit', 'button', 'reset', 'image'];
  const controls = Array.from(document.querySelectorAll('input, select, textarea'))
    .filter((el) => !skippedTypes.includes((el.getAttribute('type') || '').toLowerCase()))
    .map((el) => {
      const id = el.id || null;
      const labelFor = id ? document.querySelector('label[for="' + CSS.escape(id) + '"]') : null;
      const wrapping = el.closest('label');
      return {
        tag: el.tagName.toLowerCase(),
        type: (el.getAttribute('type') || '').toLowerCase(),
        id,
        name: el.getAttribute('name'),
        autocomplete: el.getAttribute('autocomplete'),
        required: el.hasAttribute('required') || el.getAttribute('aria-required') === 'true',
        hasLabelFor: !!labelFor,
        hasWrappedLabel: !!wrapping,
        hasAriaLabel: !!((el.getAttribute('aria-label') || '').trim()),
        hasAriaLabelledby: !!((el.getAttribute('aria-labelledby') || '').trim()),
        hasTitle: !!((el.getAttribute('title') || '').trim()),
        hasPlaceholder: !!((el.getAttribute('placeholder') || '').trim()),
        selector: u.cssPath(el),
        snippet: (el.outerHTML || '').slice(0, 240),
      };
    });

  // Кнопки именно форм: <a role="button"> и <div role="button"> — это контент
  // (их ловят content/empty-link-name и content/empty-button-name), а здесь
  // только настоящие элементы управления внутри <form>.
  const buttons = Array.from(document.querySelectorAll('button, input[type="submit"], input[type="button"]'))
    .filter((b) => u.visible(b))  // скрытые (display:none слайды) — не мешают пользователю
    .filter((b) => b.closest('form'))
    .map((b) => ({
      tag: b.tagName.toLowerCase(),
      type: (b.getAttribute('type') || '').toLowerCase(),
      name: b.getAttribute('name'),
      accessibleName: u.accessibleName(b),
      selector: u.cssPath(b),
      snippet: (b.outerHTML || '').slice(0, 200),
    }));

  return { controls, buttons };
}
"""


def run(page: object, ctx: ScanContext) -> list[Finding]:
    data = page.evaluate(COLLECT)  # type: ignore[attr-defined]
    findings: list[Finding] = []
    url = ctx.final_url

    def add(rule: str, severity: Severity, title: str, message: str, **kwargs) -> None:
        findings.append(
            Finding(
                rule=rule,
                severity=severity,
                title=title,
                message=message,
                url=url,
                source="webscope.forms",
                **kwargs,
            )
        )

    for control in data.get("controls") or []:
        labelled = (
            control["hasLabelFor"]
            or control["hasWrappedLabel"]
            or control["hasAriaLabel"]
            or control["hasAriaLabelledby"]
            or control["hasTitle"]
        )
        if not labelled:
            if control["hasPlaceholder"]:
                add(
                    "forms/placeholder-as-label",
                    Severity.MODERATE,
                    "Поле без подписи, только placeholder",
                    "Placeholder исчезает при вводе и не заменяет <label>.",
                    selector=control.get("selector"),
                    snippet=control.get("snippet"),
                    help_url="https://www.w3.org/WAI/WCAG22/Understanding/labels-or-instructions.html",
                    details={"type": control.get("type")},
                )
            else:
                add(
                    "forms/control-without-label",
                    Severity.SERIOUS,
                    "Поле формы без подписи",
                    "У элемента управления нет <label>, aria-label или title.",
                    selector=control.get("selector"),
                    snippet=control.get("snippet"),
                    help_url="https://www.w3.org/WAI/WCAG22/Understanding/labels-or-instructions.html",
                    details={"type": control.get("type")},
                )

        if not control.get("name") and control.get("tag") != "select":
            add(
                "forms/control-without-name",
                Severity.MODERATE,
                "Поле без атрибута name",
                "Без name значение не отправится в форму (кроме JS-обработчиков).",
                selector=control.get("selector"),
                snippet=control.get("snippet"),
                details={"type": control.get("type")},
            )

        if control.get("type") == "email" and not control.get("autocomplete"):
            add(
                "forms/email-without-autocomplete",
                Severity.MINOR,
                "email без autocomplete",
                'Для email ожидается autocomplete="email" — ускоряет ввод и помогает скринридерам.',
                selector=control.get("selector"),
                snippet=control.get("snippet"),
            )

    for button in data.get("buttons") or []:
        if not (button.get("accessibleName") or "").strip():
            add(
                "forms/submit-without-accessible-name",
                Severity.SERIOUS,
                "Кнопка без доступного имени",
                "У кнопки нет текста, aria-label или title.",
                selector=button.get("selector"),
                snippet=button.get("snippet"),
                help_url="https://www.w3.org/WAI/WCAG22/Understanding/button-name.html",
            )

    return findings
