"""Адаптивность: горизонтальный overflow и размер целей касания.

Overflow на 320px — самая частая жалоба пользователей на мобильных и одна из самых
проверяемых вещей в EAA/ADA-контексте. Размер цели касания — WCAG 2.2, критерий 2.5.8.
"""

from __future__ import annotations

from ..context import ScanContext
from ..models import Finding, Severity

VIEWPORTS = ((320, 640), (768, 1024))
MIN_TARGET_PX = 24

COLLECT = r"""
() => {
  const u = window.__webscopeUtils;
  const docW = document.documentElement.clientWidth;
  const scrollW = document.documentElement.scrollWidth;

  const offenders = Array.from(document.querySelectorAll('body *'))
    .filter((el) => {
      const rect = el.getBoundingClientRect();
      if (rect.width === 0 || rect.height === 0) return false;
      const style = getComputedStyle(el);
      if (style.position === 'fixed' || style.visibility === 'hidden' || style.display === 'none') return false;
      return rect.right > docW + 1 || rect.left < -1;
    })
    .slice(0, 8)
    .map((el) => {
      const rect = el.getBoundingClientRect();
      return {
        selector: u.cssPath(el),
        right: Math.round(rect.right),
        width: Math.round(rect.width),
        snippet: (el.outerHTML || '').slice(0, 200),
      };
    });

  const smallTargets = Array.from(document.querySelectorAll('a, button, input, select, textarea, [role="button"]'))
    .filter((el) => {
      const rect = el.getBoundingClientRect();
      if (rect.width === 0 || rect.height === 0) return false;
      const style = getComputedStyle(el);
      if (style.visibility === 'hidden' || style.display === 'none') return false;
      return rect.width < 24 || rect.height < 24;
    })
    .slice(0, 8)
    .map((el) => {
      const rect = el.getBoundingClientRect();
      return {
        selector: u.cssPath(el),
        width: Math.round(rect.width),
        height: Math.round(rect.height),
        snippet: (el.outerHTML || '').slice(0, 200),
      };
    });

  return { clientWidth: docW, scrollWidth: scrollW, offenders, smallTargets };
}
"""


def run(page: object, ctx: ScanContext) -> list[Finding]:
    findings: list[Finding] = []
    url = ctx.final_url
    original = page.viewport_size  # type: ignore[attr-defined]

    def add(rule: str, severity: Severity, title: str, message: str, **kwargs) -> None:
        findings.append(
            Finding(
                rule=rule,
                severity=severity,
                title=title,
                message=message,
                url=url,
                source="webscope.viewport",
                **kwargs,
            )
        )

    try:
        for width, height in VIEWPORTS:
            page.set_viewport_size({"width": width, "height": height})  # type: ignore[attr-defined]
            page.wait_for_timeout(250)  # type: ignore[attr-defined]
            data = page.evaluate(COLLECT)  # type: ignore[attr-defined]

            client = data.get("clientWidth") or width
            scroll = data.get("scrollWidth") or width
            if scroll > client + 1:
                add(
                    "viewport/horizontal-overflow",
                    Severity.SERIOUS,
                    f"Горизонтальный скролл при ширине {width}px",
                    f"Ширина документа {scroll}px больше ширины окна {client}px — появляется горизонтальная прокрутка.",
                    details={"viewport": width, "scrollWidth": scroll, "clientWidth": client},
                    help_url="https://www.w3.org/WAI/WCAG22/Understanding/reflow.html",
                )
                for offender in data.get("offenders") or []:
                    add(
                        "viewport/overflowing-element",
                        Severity.MODERATE,
                        "Элемент выходит за границу экрана",
                        f"Правый край элемента {offender.get('right')}px при окне {client}px.",
                        selector=offender.get("selector"),
                        snippet=offender.get("snippet"),
                        details={"viewport": width},
                    )

            # Размер целей касания проверяем только на мобильном вьюпорте, чтобы не плодить дубли.
            if width == VIEWPORTS[0][0]:
                for target in data.get("smallTargets") or []:
                    add(
                        "viewport/target-size",
                        Severity.MINOR,
                        "Размер цели касания меньше 24×24",
                        f"{target.get('width')}×{target.get('height')}px — WCAG 2.2 AA (2.5.8) требует не меньше 24×24.",
                        selector=target.get("selector"),
                        snippet=target.get("snippet"),
                        help_url="https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html",
                    )
    finally:
        if original:
            page.set_viewport_size(original)  # type: ignore[attr-defined]

    return findings
