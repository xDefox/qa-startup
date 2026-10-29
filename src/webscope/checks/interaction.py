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

  // Непрозрачный слой: сплошной фон или фоновая картинка (как t-bgimg у Tilda).
  const opaque = (n) => {
    const s = getComputedStyle(n);
    const m = (s.backgroundColor || '').match(/rgba?\(([^)]+)\)/);
    if (m) {
      const parts = m[1].split(',');
      const alpha = parts.length > 3 ? parseFloat(parts[3]) : 1;
      if (alpha >= 0.9) return true;
    }
    return !!s.backgroundImage && s.backgroundImage !== 'none';
  };

  const covers = (outer, inner) => (
    outer.left <= inner.left + 2 && outer.top <= inner.top + 2
    && outer.right >= inner.right - 2 && outer.bottom >= inner.bottom - 2
  );

  // Прозрачная интерактивная обёртка (Tilda: <a class="tn-atom"> с нулевым
  // фоном поверх фоновой картинки-«атома») — клик доезжает до ссылки:
  // элементFromPoint её и возвращает. Это не перекрытие.
  const wrapperTransparent = (hit) => {
    const s = getComputedStyle(hit);
    const m = (s.backgroundColor || '').match(/rgba?\(([^)]+)\)/);
    let alpha = 1;
    if (m) {
      const parts = m[1].split(',');
      alpha = parts.length > 3 ? parseFloat(parts[3]) : 1;
    }
    return alpha < 0.05 && (!s.backgroundImage || s.backgroundImage === 'none');
  };

  const interactive = (node) => node && node.matches
    && node.matches('a[href], button, [role="button"], input[type="submit"], input[type="button"]');

  const sameHrefReachable = (hit, target) => {
    if (!target) return false;
    // Блокер сам ссылка с той же целью.
    const own = hit.closest && hit.closest('a, button, [role="button"]');
    if (own && (own.href || '') === target) return true;
    // Внутри блокера лежит ссылка с той же целью — клик доедет (Tilda-фиды
    // перехватывают клик на обёртке, но ведут ровно туда же).
    const inside = hit.querySelector && hit.querySelector('a[href]');
    if (!inside) return false;
    return Array.from(hit.querySelectorAll('a[href]')).some((a) => (a.href || '') === target);
  };

  const nodes = Array.from(document.querySelectorAll('a, button, [role="button"], input[type="submit"], input[type="button"]'))
    .filter((el) => {
      const style = getComputedStyle(el);
      if (style.visibility === 'hidden' || style.display === 'none' || style.pointerEvents === 'none') return false;
      const rect = el.getBoundingClientRect();
      if (rect.width < 8 || rect.height < 8) return false;
      // Проверяем только пересечение с экраном: центр элемента, лежащего за
      // краем окна, клампится на 1px мимо него — hit-test бьёт в пустоту.
      // Видимая часть должна быть осмысленной (≥8px), иначе кликать не по чему.
      const iw = window.innerWidth, ih = window.innerHeight;
      const visW = Math.min(rect.right, iw) - Math.max(rect.left, 0);
      const visH = Math.min(rect.bottom, ih) - Math.max(rect.top, 0);
      if (visW < 8 || visH < 8) return false;
      return true;
    })
    .slice(0, 25)
    .map((el) => {
      const rect = el.getBoundingClientRect();
      const iw = window.innerWidth, ih = window.innerHeight;
      // Точка клика — центр видимой части, а не центра бокса.
      const cx = Math.max(0, Math.min(iw - 1, (Math.max(rect.left, 0) + Math.min(rect.right, iw)) / 2));
      const cy = Math.max(0, Math.min(ih - 1, (Math.max(rect.top, 0) + Math.min(rect.bottom, ih)) / 2));
      let topEl = null;
      try {
        topEl = document.elementFromPoint(cx, cy);
      } catch (e) {}
      let blocked = false;
      let blocker = null;
      if (topEl && topEl !== el && !el.contains(topEl)) {
        if (sameHrefReachable(topEl, el.href || '')) {
          // Клик доходит до ссылки с той же целью — кнопка работает.
          blocked = false;
        } else if (interactive(topEl) && wrapperTransparent(topEl)) {
          // Клик получает сама интерактивная обёртка — кнопка работает.
          blocked = false;
        } else if (opaque(topEl) && covers(topEl.getBoundingClientRect(), rect)) {
          // Элемент целиком скрыт непрозрачным слоем (неактивный слайд,
          // спрятанный атом): пользователь его не видит и не кликает.
          return null;
        } else {
          blocked = true;
          blocker = (topEl.getAttribute('class') || topEl.tagName).slice(0, 80);
        }
      }
      if (!blocked) return null;
      return {
        selector: u.cssPath(el),
        text: (el.innerText || el.value || el.getAttribute('aria-label') || '').slice(0, 60).trim(),
        blocked,
        blocker,
        width: Math.round(rect.width),
        height: Math.round(rect.height),
        snippet: (el.outerHTML || '').slice(0, 220),
      };
    })
    .filter(Boolean);
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
