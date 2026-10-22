"""Поведенческая проверка кликабельности: можно ли реально кликнуть по кнопке/ссылке.

Вместо «кнопка меньше 24х24» — проверяем факт: перекрыта ли интерактивная
кнопка другим элементом. Именно это блокирует заявку.
"""

from __future__ import annotations

from ..context import ScanContext
from ..models import Finding, Severity

COLLECT = r"""
() => {
  const u = window.__webscopeUtils;
  const nodes = Array.from(document.querySelectorAll('a, button, [role="button"], input[type="submit"], input[type="button"]'))
    .filter((el) => {
      const style = getComputedStyle(el);
      if (style.visibility === 'hidden' || style.display === 'none' || style.pointerEvents === 'none') return false;
      const rect = el.getBoundingClientRect();
      if (rect.width < 8 || rect.height < 8) return false;
      if (rect.bottom < 0 || rect.top > window.innerHeight) return false;
      if (rect.right < 0 || rect.left > window.innerWidth) return false;
      return true;
    })
    .slice(0, 25)
    .map((el) => {
      const rect = el.getBoundingClientRect();
      const cx = Math.max(0, Math.min(window.innerWidth - 1, rect.left + rect.width / 2));
      const cy = Math.max(0, Math.min(window.innerHeight - 1, rect.top + rect.height / 2));
      let topEl = null;
      try {
        topEl = document.elementFromPoint(cx, cy);
      } catch (e) {}
      let blocked = false;
      let blocker = null;
      if (topEl && topEl !== el && !el.contains(topEl)) {
        blocked = true;
        blocker = (topEl.getAttribute('class') || topEl.tagName).slice(0, 80);
      }
      return {
        selector: u.cssPath(el),
        text: (el.innerText || el.value || el.getAttribute('aria-label') || '').slice(0, 60).trim(),
        blocked,
        blocker,
        width: Math.round(rect.width),
        height: Math.round(rect.height),
        snippet: (el.outerHTML || '').slice(0, 220),
      };
    });
  return nodes;
}
"""


def run(page: object, ctx: ScanContext) -> list[Finding]:
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
                source="webscope.interaction",
                **kwargs,
            )
        )

    try:
        data = page.evaluate(COLLECT)  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        return []

    for item in data or []:
        if not item.get("blocked"):
            continue
        label = item.get("text") or "интерактивный элемент"
        add(
            "interaction/button-blocked",
            Severity.CRITICAL,
            f"Кнопку/ссылку «{label}» нельзя кликнуть — элемент перекрыт",
            "Другой элемент перехватывает клик в центре кнопки. Из-за этого пользователь не может оставить заявку/заказ.",
            selector=item.get("selector"),
            snippet=item.get("snippet"),
            details={"blocker": item.get("blocker"), "size": f"{item.get('width')}x{item.get('height')}"},
        )

    return findings
