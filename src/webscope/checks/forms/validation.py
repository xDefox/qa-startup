"""Формы: базовые проблемы + валидация.

Базовые проверки — в forms.py. Здесь минимальный набор по валидации,
чтобы закрыть пробел, который видно на реальных сайтах.
"""

from __future__ import annotations

from ...context import ScanContext
from ...models import Finding, Severity

COLLECT = r"""
() => {
  const u = window.__webscopeUtils;
  const forms = Array.from(document.querySelectorAll('form')).map((form) => {
    const inputs = Array.from(form.querySelectorAll('input, select, textarea')).map((el) => {
      const type = (el.getAttribute('type') || '').toLowerCase();
      const name = (el.getAttribute('name') || '').toLowerCase();
      const id = el.getAttribute('id') || '';
      const labelText = id ? (document.querySelector('label[for="' + CSS.escape(id) + '"]')?.textContent || '') : '';
      const placeholder = (el.getAttribute('placeholder') || '').toLowerCase();
      const ariaLabel = (el.getAttribute('aria-label') || '').toLowerCase();
      const text = (labelText + ' ' + placeholder + ' ' + ariaLabel + ' ' + name).toLowerCase();
      return {
        tag: el.tagName.toLowerCase(),
        type,
        name: el.getAttribute('name'),
        hasRequired: el.hasAttribute('required') || el.getAttribute('aria-required') === 'true',
        inputmode: el.getAttribute('inputmode'),
        pattern: el.getAttribute('pattern'),
        autocomplete: el.getAttribute('autocomplete'),
        text,
        looksRequired: /(имя|фамил|телефон|phone|mobile|e-?mail|почт|парол)/.test(text) && type !== 'hidden' && type !== 'submit' && type !== 'button',
        selector: u.cssPath(el),
        snippet: (el.outerHTML || '').slice(0, 240),
      };
    });
    return {
      selector: u.cssPath(form),
      snippet: (form.outerHTML || '').slice(0, 240),
      novalidate: form.hasAttribute('novalidate'),
      noValidate: form.noValidate,
      inputs,
    };
  });
  return forms;
}
"""


def run(page: object, ctx: ScanContext) -> list[Finding]:
    try:
        forms = page.evaluate(COLLECT)  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 - проверка не критична
        return []
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
                source="webscope.forms.validation",
                **kwargs,
            )
        )

    for form in forms or []:
        if form.get("novalidate") or form.get("noValidate"):
            add(
                "forms/novalidate",
                Severity.SERIOUS,
                "Форма отключает встроенную браузерную валидацию",
                "У формы есть novalidate. Если нет своей валидации — заявка может уйти с ошибками.",
                selector=form.get("selector"),
                snippet=form.get("snippet"),
            )

        for inp in form.get("inputs") or []:
            inp_type = inp.get("type") or ""
            if inp_type == "text":
                name = (inp.get("name") or "").lower()
                text = inp.get("text") or ""
                if "mail" in name or "email" in text or "e-mail" in text:
                    add(
                        "forms/email-wrong-type",
                        Severity.MODERATE,
                        "Поле email имеет тип text",
                        'Для email лучше использовать type="email".',
                        selector=inp.get("selector"),
                        snippet=inp.get("snippet"),
                    )
                elif ("phone" in name or "телефон" in text or "mobile" in text) and not inp.get("inputmode"):
                    add(
                        "forms/tel-missing-inputmode",
                        Severity.MINOR,
                        "У поля телефона нет inputmode",
                        'Добавьте inputmode="tel" для удобства на мобильных устройствах.',
                        selector=inp.get("selector"),
                        snippet=inp.get("snippet"),
                    )
            elif inp_type == "email" and not inp.get("inputmode"):
                pass  # не критично

        # Не угадываем обязательность по смыслу — убираем эвристику.

    return findings
