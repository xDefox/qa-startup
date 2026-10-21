"""Контент и семантика страницы.

Проверяем то, что ловится без знания предметной области: язык документа, заголовки,
alt-тексты, доступные имена, дубли идентификаторов.
"""

from __future__ import annotations

from ..context import ScanContext
from ..models import Finding, Severity

COLLECT = r"""
() => {
  const u = window.__webscopeUtils;
  const doc = document;
  const pick = (el, extra) => Object.assign({ selector: u.cssPath(el), snippet: (el.outerHTML || '').slice(0, 240) }, extra || {});

  const headings = Array.from(doc.querySelectorAll('h1,h2,h3,h4,h5,h6')).map((h) => ({
    level: Number(h.tagName[1]),
    text: u.text(h).slice(0, 120),
    selector: u.cssPath(h),
  }));

  const images = Array.from(doc.querySelectorAll('img'))
    .filter((i) => !i.hasAttribute('alt'))
    .map((i) => pick(i, { src: i.getAttribute('src') || '' }));

  const iframes = Array.from(doc.querySelectorAll('iframe'))
    .filter((f) => !(f.getAttribute('title') || '').trim() && !(f.getAttribute('aria-label') || '').trim())
    .map((f) => pick(f, { src: f.getAttribute('src') || '' }));

  const emptyLinks = Array.from(doc.querySelectorAll('a'))
    .filter((a) => u.visible(a) && u.accessibleName(a) === '')
    .map((a) => pick(a, { href: a.getAttribute('href') || '' }));

  const emptyButtons = Array.from(doc.querySelectorAll('button, [role="button"]'))
    .filter((b) => u.visible(b) && u.accessibleName(b) === '')
    .map((b) => pick(b));

  const ids = Array.from(doc.querySelectorAll('[id]')).map((e) => e.id).filter(Boolean);
  const duplicateIds = Array.from(new Set(ids.filter((id, idx) => ids.indexOf(id) !== idx)));

  const meta = (name) => {
    const el = doc.querySelector('meta[name="' + name + '"]');
    return el ? (el.getAttribute('content') || '') : null;
  };

  return {
    lang: doc.documentElement.getAttribute('lang'),
    title: doc.title || '',
    description: meta('description'),
    viewport: meta('viewport'),
    charset: doc.characterSet || '',
    protocol: location.protocol,
    headings,
    images,
    iframes,
    emptyLinks,
    emptyButtons,
    duplicateIds,
  };
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
                source="webscope.content",
                **kwargs,
            )
        )

    if not (data.get("lang") or "").strip():
        add(
            "content/missing-lang",
            Severity.SERIOUS,
            "Не задан язык документа",
            "У <html> нет атрибута lang — скринридеры не смогут выбрать голосовой движок.",
            help_url="https://www.w3.org/WAI/WCAG22/Understanding/language-of-page.html",
        )

    if not (data.get("title") or "").strip():
        add(
            "content/missing-title",
            Severity.SERIOUS,
            "Пустой title",
            "У страницы нет заголовка <title> — вкладка браузера и поисковая выдача будут пустыми.",
            help_url="https://www.w3.org/WAI/WCAG22/Understanding/page-title.html",
        )

    if not (data.get("description") or "").strip():
        add(
            "content/missing-description",
            Severity.MODERATE,
            "Нет meta description",
            "Сниппет в поисковой выдаче будет генерироваться автоматически.",
        )

    if not (data.get("viewport") or "").strip():
        add(
            "content/missing-viewport",
            Severity.SERIOUS,
            "Нет viewport meta",
            "Страница не адаптируется под мобильные экраны.",
            help_url="https://www.w3.org/WAI/WCAG22/Understanding/adapt-content-to-keyboard.html",
        )

    headings = data.get("headings") or []
    h1_count = sum(1 for h in headings if h["level"] == 1)
    if h1_count == 0:
        add(
            "content/no-h1",
            Severity.MODERATE,
            "Нет заголовка первого уровня",
            "На странице нет <h1> — структура документа не отражает иерархию.",
        )
    elif h1_count > 1:
        add(
            "content/multiple-h1",
            Severity.MODERATE,
            "Несколько <h1>",
            f"На странице {h1_count} заголовка первого уровня — обычно ожидается один.",
        )

    previous = 0
    for heading in headings:
        level = heading["level"]
        if previous and level > previous + 1:
            add(
                "content/heading-order",
                Severity.MINOR,
                "Нарушен порядок заголовков",
                f"После h{previous} идёт h{level}: уровень пропущен.",
                selector=heading.get("selector"),
                snippet=(heading.get("text") or "")[:240],
            )
        previous = level

    for image in data.get("images") or []:
        add(
            "content/image-alt",
            Severity.SERIOUS,
            "Изображение без alt",
            "У <img> нет атрибута alt — содержание изображения недоступно для скринридера.",
            selector=image.get("selector"),
            snippet=image.get("snippet"),
            help_url="https://www.w3.org/WAI/WCAG22/Understanding/non-text-content.html",
            details={"src": image.get("src")},
        )

    for iframe in data.get("iframes") or []:
        add(
            "content/iframe-title",
            Severity.MODERATE,
            "iframe без заголовка",
            "У <iframe> нет title или aria-label — невозможно понять, что внутри.",
            selector=iframe.get("selector"),
            snippet=iframe.get("snippet"),
            help_url="https://www.w3.org/WAI/WCAG22/Understanding/frame-title.html",
        )

    for link in data.get("emptyLinks") or []:
        add(
            "content/empty-link-name",
            Severity.SERIOUS,
            "Ссылка без доступного имени",
            "Текст ссылки пуст — пользователь скринридера не поймёт, куда ведёт переход.",
            selector=link.get("selector"),
            snippet=link.get("snippet"),
            help_url="https://www.w3.org/WAI/WCAG22/Understanding/link-name-in-context.html",
            details={"href": link.get("href")},
        )

    for button in data.get("emptyButtons") or []:
        add(
            "content/empty-button-name",
            Severity.SERIOUS,
            "Кнопка без доступного имени",
            "У кнопки нет текста, aria-label или title.",
            selector=button.get("selector"),
            snippet=button.get("snippet"),
            help_url="https://www.w3.org/WAI/WCAG22/Understanding/button-name.html",
        )

    for duplicate in data.get("duplicateIds") or []:
        add(
            "content/duplicate-id",
            Severity.MODERATE,
            "Дублирующийся id",
            f'id="{duplicate}" встречается на странице больше одного раза — ломает label/for и aria-labelledby.',
            details={"id": duplicate},
            help_url="https://www.w3.org/WAI/WCAG22/Understanding/duplicate-id-2.html",
        )

    return findings
