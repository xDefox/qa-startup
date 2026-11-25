"""Мобильная вёрстка: реальная горизонтальная прокрутка на узком экране.

Проверяем только 320 px — самый узкий телефон. Если документ шире окна,
клиент видит обрезанный сайт и вынужден скроллить вбок; это ломает чтение
и кнопки. Размеры целей касания и «красивость» здесь не оцениваем: это не
повод платить за проверку.
"""

from __future__ import annotations

from ..context import ScanContext
from ..models import Finding, Severity

VIEWPORT_WIDTH = 320
VIEWPORT_HEIGHT = 640

# Порог выхода за край окна в px: меньше — считаем шумом. Браузерные округления,
# дробные пиксели и «кнопка на 2–3 мм вправа» (≈6–8px при ширине ~320px)
# почти всегда не мешают клиенту, а десятки таких находок только шумят в отчёте.
OVERFLOW_MIN_PX = 8

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
      return rect.right > docW + __OVERFLOW_MIN_PX__ || rect.left < -__OVERFLOW_MIN_PX__;
    })
    .slice(0, 5)
    .map((el) => {
      const rect = el.getBoundingClientRect();
      return {
        selector: u.cssPath(el),
        right: Math.round(rect.right),
        width: Math.round(rect.width),
        snippet: (el.outerHTML || '').slice(0, 200),
      };
    });

  return { clientWidth: docW, scrollWidth: scrollW, offenders };
}
"""


def run(page: object, ctx: ScanContext) -> list[Finding]:
    findings: list[Finding] = []
    url = ctx.final_url
    original = page.viewport_size  # type: ignore[attr-defined]

    try:
        page.set_viewport_size({"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT})  # type: ignore[attr-defined]
        page.wait_for_timeout(250)  # type: ignore[attr-defined]
        data = page.evaluate(COLLECT.replace("__OVERFLOW_MIN_PX__", str(OVERFLOW_MIN_PX)))  # type: ignore[attr-defined]

        client = data.get("clientWidth") or VIEWPORT_WIDTH
        scroll = data.get("scrollWidth") or VIEWPORT_WIDTH
        if scroll > client + OVERFLOW_MIN_PX:
            offenders = data.get("offenders") or []
            details: dict[str, object] = {
                "viewport": VIEWPORT_WIDTH,
                "scrollWidth": scroll,
                "clientWidth": client,
            }
            if offenders:
                details["offenders"] = offenders
            findings.append(
                Finding(
                    rule="viewport/horizontal-overflow",
                    severity=Severity.SERIOUS,
                    title=f"На телефоне сайт прокручивается вбок ({scroll}px при экране {client}px)",
                    message=(
                        "Документ шире экрана: часть контента и кнопок уходит за правый край. "
                        "Клиенту приходится скроллить страницу вбок, чтобы прочитать текст или нажать кнопку."
                    ),
                    url=url,
                    source="webscope.viewport",
                    details=details,
                    help_url="https://www.w3.org/WAI/WCAG22/Understanding/reflow.html",
                ),
            )
            for offender in offenders:
                findings.append(
                    Finding(
                        rule="viewport/overflowing-element",
                        severity=Severity.MODERATE,
                        title="Элемент выходит за границу экрана",
                        message=(
                            f"Правый край элемента {offender.get('right')}px при ширине окна {client}px — "
                            "это и создаёт горизонтальную прокрутку."
                        ),
                        url=url,
                        selector=offender.get("selector"),
                        snippet=offender.get("snippet"),
                        source="webscope.viewport",
                        details={"viewport": VIEWPORT_WIDTH},
                    ),
                )
    finally:
        if original:
            page.set_viewport_size(original)  # type: ignore[attr-defined]

    return findings
