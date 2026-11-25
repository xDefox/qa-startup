"""Мобильная реальность: три проверки при viewport-эмуляции телефона (320×640).

Остальные проверки сканируют десктоп (1280×800), поэтому настоящие мобильные
проблемы они почти не видят. Здесь:

- `viewport/meta-viewport` — meta viewport есть, но в неправильном формате
  (не `width=device-width` / битый `initial-scale` / `user-scalable=no`);
  *присутствие* отсутствующего тега ловит `content/missing-viewport`;
- `viewport/horizontal-scroll` — скроллируемые блоки и документ не отвечают
  на скролл (``touch-action`` на html/body блокирует горизонтальный пан,
  скроллируемый блок с `touch-action: none/pan-y` не двигается).
  Правило информационно (Severity.MINOR): желание разработчика, не то,
  за что владелец сайта платит. Владелец сайта на это информирован;
- `viewport/target-size` — ссылки/кнопки меньше 24×24 px (WCAG 2.2 2.5.8
  Target Size (Minimum) — формат ACCEPTANCE в report.py).
"""

from __future__ import annotations

from ..context import ScanContext
from ..models import Finding, Severity
from .viewport import VIEWPORT_HEIGHT, VIEWPORT_WIDTH

# WCAG 2.2 2.5.8 — минимальный размер цели касания (44×44 — уже крепость,
# блокер не тот, поэтому порог мягче: по ACCEPTANCE в report.py — 24×24).
TARGET_MIN_PX = 24

COLLECT = r"""
(minTarget) => {
  const u = window.__webscopeUtils;
  const doc = document.documentElement;
  const body = document.body;

  // --- 1. meta viewport: формат (присутствие — content/missing-viewport) ---
  const meta = document.querySelector('meta[name="viewport"]');
  let metaInfo = { present: !!meta, valid: false, reason: null, content: '' };
  if (meta) {
    const raw = (meta.getAttribute('content') || '').trim();
    metaInfo.content = raw;
    const parts = {};
    for (const chunk of raw.split(',')) {
      const eq = chunk.indexOf('=');
      if (eq === -1) continue;
      const key = chunk.slice(0, eq).trim().toLowerCase();
      const value = chunk.slice(eq + 1).trim().replace(/^"|"$/g, '');
      if (key) parts[key] = value;
    }
    const width = (parts['width'] || '').toLowerCase();
    const scaleRaw = parts['initial-scale'];
    const scale = parseFloat(scaleRaw || '');
    const userScalable = (parts['user-scalable'] || '').toLowerCase();
    if (width !== 'device-width') metaInfo.reason = 'width';
    else if (scaleRaw && (!isFinite(scale) || scale <= 0 || scale > 3)) metaInfo.reason = 'initial-scale';
    else if (userScalable === 'no' || userScalable === '0') metaInfo.reason = 'user-scalable';
    metaInfo.valid = !metaInfo.reason;
  }

  // --- 2. горизонтальный скролл: контейнеры, где он должен работать, и документ ---
  // touchBlocks — состояние, когда touch-скроллинг не работает вообще
  // (touch-action: none) или запрещён для горизонтального панирования (pan-y).
  const touchBlocks = (el) => {
    const action = getComputedStyle(el).touchAction;
    return action === 'none' || action === 'pan-y';
  };
  const docHorizontal = doc.scrollWidth > doc.clientWidth + 1;
  const rootBlocked = docHorizontal && (touchBlocks(doc) || (body && touchBlocks(body)));

  const scrollBlocks = [];
  Array.from(document.querySelectorAll('body *')).forEach((el) => {
    if (!u.visible(el)) return;
    const style = getComputedStyle(el);
    const overflowX = style.overflowX;
    if (!['auto', 'scroll', 'overlay'].includes(overflowX)) return;
    const room = el.scrollWidth - el.clientWidth;
    if (room <= 1) return; // горизонтального контента нет — скролла и не ждём
    const origin = el.scrollLeft;
    const target = Math.min(origin + 8, room - 1);
    if (target <= origin) return; // уже доскроллили до конца
    el.scrollLeft = target;
    const programmatic = el.scrollLeft >= target - 1;
    el.scrollLeft = origin;
    if (!programmatic || touchBlocks(el)) {
      scrollBlocks.push({
        selector: u.cssPath(el),
        tag: el.tagName.toLowerCase(),
        overflowX,
        touchAction: style.touchAction,
        scrollWidth: el.scrollWidth,
        clientWidth: el.clientWidth,
        snippet: (el.outerHTML || '').slice(0, 200),
      });
    }
  });

  // --- 3. цели касания: ссылки/кнопки меньше 24×24 ---
  const targets = Array.from(document.querySelectorAll('a[href], area[href], button, [role="button"]'))
    .filter((el) => u.visible(el))
    .map((el) => {
      const rect = el.getBoundingClientRect();
      return {
        selector: u.cssPath(el),
        tag: el.tagName.toLowerCase(),
        width: Math.round(rect.width),
        height: Math.round(rect.height),
        snippet: (el.outerHTML || '').slice(0, 200),
      };
    })
    .filter((t) => t.width > 0 && t.height > 0 && (t.width < minTarget || t.height < minTarget))
    .slice(0, 10);

  return { metaInfo, docHorizontal, rootBlocked, scrollBlocks, targets };
}
"""


def _meta_viewport_findings(data: dict, url: str) -> list[Finding]:
    """Присутствие отсутствующего viewport-тега — другая проверка; здесь — только формат."""
    info = data.get("metaInfo") or {}
    if not (info.get("present") and not info.get("valid")):
        return []
    reason = info.get("reason")
    severity = Severity.SERIOUS if reason == "width" else Severity.MODERATE
    message_by_reason = {
        "width": "Атрибут width отсутствует или не `device-width` — при открытии на телефоне сайт не подстраивается под экран.",
        "initial-scale": "Неверный `initial-scale` — страница не показывается в нужном масштабе при загрузке.",
        "user-scalable": "`user-scalable=no` запрещает зум — клиенту сложнее читать мелкий текст.",
    }
    return [
        Finding(
            rule="viewport/meta-viewport",
            severity=severity,
            title="Meta viewport в неправильном формате",
            message=message_by_reason.get(reason or "", "Формат meta viewport не соответствует рекомендованному."),
            url=url,
            source="webscope.mobile",
            details={"content": info.get("content", ""), "reason": reason},
            help_url="https://developer.mozilla.org/en-US/docs/Web/HTML/Viewport_meta_tag",
        ),
    ]


def _horizontal_scroll_findings(data: dict, url: str) -> list[Finding]:
    """Блоки/документ, где горизонтальный скролл теоретически есть, но не отвечает.

    Информационное правило (Severity.MINOR): информирует, но не считается
    дефектом сайта.
    """
    findings: list[Finding] = []
    if data.get("rootBlocked"):
        findings.append(
            Finding(
                rule="viewport/horizontal-scroll",
                severity=Severity.MINOR,
                title="Горизонтальный скролл документа заблокирован",
                message=(
                    "Документ шире экрана, но touch-action на html/body запрещает панирование вбок — "
                    "клиент не просмотрит обрезанную часть. (Информационно: желание разработчика, "
                    "не то, за что владелец сайта платит.)"
                ),
                url=url,
                selector="html",
                source="webscope.mobile",
                details={"viewport": VIEWPORT_WIDTH},
                help_url="https://developer.mozilla.org/en-US/docs/Web/CSS/touch-action",
            ),
        )
    for block in data.get("scrollBlocks") or []:
        findings.append(
            Finding(
                rule="viewport/horizontal-scroll",
                severity=Severity.MINOR,
                title="Горизонтальный скролл не работает",
                message=(
                    f"Блок прокручивается горизонтально (scrollWidth {block['scrollWidth']}px "
                    f"> clientWidth {block['clientWidth']}px), но скролл не отвечает на сдвиг "
                    "или touch-action запрещает горизонтальный панирование. "
                    "(Информационно: желание разработчика, не то, за что владелец сайта платит.)"
                ),
                url=url,
                selector=block.get("selector"),
                snippet=block.get("snippet"),
                source="webscope.mobile",
                details={
                    "viewport": VIEWPORT_WIDTH,
                    "overflowX": block.get("overflowX"),
                    "touchAction": block.get("touchAction"),
                    "scrollWidth": block.get("scrollWidth"),
                    "clientWidth": block.get("clientWidth"),
                },
                help_url="https://developer.mozilla.org/en-US/docs/Web/CSS/touch-action",
            ),
        )
    return findings


def _target_size_findings(data: dict, url: str) -> list[Finding]:
    """Ссылки/кнопки меньше 24×24 px — тап по ним часто попадает мимо."""
    findings: list[Finding] = []
    for target in data.get("targets") or []:
        width = target["width"]
        height = target["height"]
        findings.append(
            Finding(
                rule="viewport/target-size",
                severity=Severity.MODERATE,
                title=f"Цель касания меньше 24×24 px ({width}×{height})",
                message=(
                    f"Элемент ({target['tag']}) занимает {width}×{height} px — меньше минимума "
                    f"{TARGET_MIN_PX}×{TARGET_MIN_PX} по WCAG 2.2 Target Size (Minimum). Тап по такой цели может упасть."
                ),
                url=url,
                selector=target.get("selector"),
                snippet=target.get("snippet"),
                source="webscope.mobile",
                details={"width": width, "height": height},
                help_url="https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum",
            ),
        )
    return findings


def run(page: object, ctx: ScanContext) -> list[Finding]:
    """Мобильные проверки при viewport-эмуляции 320×640."""
    findings: list[Finding] = []
    url = ctx.final_url
    original = page.viewport_size  # type: ignore[attr-defined]

    try:
        page.set_viewport_size({"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT})  # type: ignore[attr-defined]
        page.wait_for_timeout(250)  # type: ignore[attr-defined]
        data = page.evaluate(COLLECT, TARGET_MIN_PX)  # type: ignore[attr-defined]

        findings.extend(_meta_viewport_findings(data, url))
        findings.extend(_horizontal_scroll_findings(data, url))
        findings.extend(_target_size_findings(data, url))
    finally:
        if original:
            page.set_viewport_size(original)  # type: ignore[attr-defined]

    return findings
