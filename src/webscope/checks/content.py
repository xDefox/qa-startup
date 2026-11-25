"""Контент и семантика страницы.

Проверяем то, что ловится без знания предметной области: язык документа, заголовки,
alt-тексты, доступные имена, дубли идентификаторов.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin, urlparse

import httpx

from ..context import ScanContext
from ..credscope import strip_out_of_scope_headers
from ..models import Finding, Severity
from ..netguard import GuardedTransport

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

  // Ссылки на эту же страницу (href="#..."): меню, слайдеры, якоря — проверяем
  // так же, как обычные. Пустая ссылка <a href="#"></a> без имени недоступна
  // скринридеру независимо от того, куда она ведёт, а именно в якорных ссылках
  // иконочные кнопки чаще всего остаются без доступного имени.
  const emptyLinks = Array.from(doc.querySelectorAll('a'))
    .filter((a) => a.getAttribute('data-testid') === null && a.getAttribute('data-qa') === null)
    .filter((a) => a.getAttribute('aria-hidden') !== 'true')
    .filter((a) => u.visible(a) && u.accessibleName(a) === '')
    .map((a) => pick(a, { href: a.getAttribute('href') || '' }));

  // Один дефект — одна находка: <a> (даже с role="button") уже пойман выше
  // как ссылка, кнопки внутри <form> — их ловит forms/submit-without-accessible-name.
  const emptyButtons = Array.from(doc.querySelectorAll('button, [role="button"]'))
    .filter((b) => b.getAttribute('data-testid') === null && b.getAttribute('data-qa') === null)
    .filter((b) => b.getAttribute('aria-hidden') !== 'true')
    .filter((b) => u.visible(b) && u.accessibleName(b) === '')
    .filter((b) => !(b.tagName === 'A' && b.hasAttribute('href')))
    .filter((b) => !b.closest('form'))
    .map((b) => pick(b));

  const ids = Array.from(doc.querySelectorAll('[id]')).map((e) => e.id).filter(Boolean);
  const duplicateIds = Array.from(new Set(ids.filter((id, idx) => ids.indexOf(id) !== idx)));

  const meta = (name) => {
    const el = doc.querySelector('meta[name="' + name + '"]');
    return el ? (el.getAttribute('content') || '') : null;
  };

  // Open Graph и Twitter Card — как ссылка выглядит при репосте в мессенджер/соцсеть.
  const og = (prop) => {
    const el = doc.querySelector('meta[property="' + prop + '"]');
    return el ? (el.getAttribute('content') || '').trim() : null;
  };
  const twitter = (name) => {
    const el = doc.querySelector('meta[name="' + name + '"]');
    return el ? (el.getAttribute('content') || '').trim() : null;
  };

  return {
    lang: doc.documentElement.getAttribute('lang'),
    title: doc.title || '',
    description: meta('description'),
    viewport: meta('viewport'),
    charset: doc.characterSet || '',
    hasCharsetMeta: !!doc.querySelector('meta[charset]'),
    protocol: location.protocol,
    ogTitle: og('og:title'),
    ogDescription: og('og:description'),
    ogImage: og('og:image'),
    ogUrl: og('og:url'),
    twitterCard: twitter('twitter:card'),
    twitterImage: twitter('twitter:image'),
    canonical: (doc.querySelector('link[rel="canonical"]') || {}).href || '',
    ogSiteName: og('og:site_name'),
    jsonLdPresent: doc.querySelectorAll('script[type="application/ld+json"]').length > 0,
    jsonLdCount: doc.querySelectorAll('script[type="application/ld+json"]').length,
    headings,
    images,
    iframes,
    emptyLinks,
    emptyButtons,
    duplicateIds,
  };
}
"""


def _check_social_card(data: dict, add) -> None:
    """Проверяет, как ссылка будет выглядеть при репосте (og-теги).

    Когда владелец или клиент копирует ссылку в Telegram/WhatsApp/VK, мессенджер
    читает Open Graph. Без og:title страница выглядит как голый имя вкладки, без
    og:image — как пустая серая карточка. Проверяем только og:title и og:image:
    они напрямую видны при репосте. og:description мессенджеры часто берут из
    первого абзаца самой страницы, поэтому его отсутствие не считаем находкой.
    """
    og_title = data.get("ogTitle")
    og_image = data.get("ogImage")

    if not og_title:
        add(
            "content/missing-og-title",
            Severity.MINOR,
            "Нет og:title — ссылка при репосте без заголовка",
            "Мессенджер и соцсеть не найдут заголовка для карточки и покажут "
            "пустое имя вкладки вместо понятного названия страницы.",
            help_url="https://ogp.me/#optional",
        )

    if not og_image:
        add(
            "content/missing-og-image",
            Severity.MODERATE,
            "Нет og:image — ссылка при репосте без картинки",
            "При репосте в мессенджер или соцсеть карточка будет без изображения: "
            "серый пустой прямоугольник вместо обложки, которую клиенты замечают в ленте.",
            help_url="https://ogp.me/#optional",
        )


def _check_broken_images(data: dict, ctx: ScanContext, add) -> None:
    """Битые картинки на странице — подтверждённые 4xx/5xx (сервер вернул ошибку).

    Сканер увидит это только в отчёте, но владельцу сайта это важно: картинка с
    битым адресом часто не видна пользователю, контент — тоже. Таймауты не
    считаем дефектом страницы.
    """
    page_host = urlparse(ctx.final_url).netloc
    candidates: list[str] = []
    seen: set[str] = set()
    for image in data.get("images") or []:
        src = (image.get("src") or "").strip()
        if not src or src.startswith(("data:", "blob:")):
            continue
        resolved = urljoin(ctx.final_url, src)
        parsed = urlparse(resolved)
        if parsed.scheme not in {"http", "https"} or parsed.netloc != page_host:
            continue
        if resolved not in seen:
            seen.add(resolved)
            candidates.append(resolved)

    if not candidates:
        return

    with httpx.Client(
        timeout=httpx.Timeout(8.0, connect=4.0),
        follow_redirects=True,
        transport=GuardedTransport(allow_private=ctx.allow_private),
        headers=ctx.site_headers or None,
        event_hooks={"request": [strip_out_of_scope_headers(ctx.final_url)]},
    ) as client:

        def probe(url: str) -> tuple[str, int | None]:
            try:
                response = client.head(url)
                if response.status_code in (403, 405, 501):
                    response = client.get(url)
                return url, response.status_code
            except Exception:  # noqa: BLE001 - сеть не должна ронять скан
                return url, None

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(probe, candidates))

    for url, status in results:
        if status is not None and status >= 400:
            severity = Severity.MODERATE if status < 500 else Severity.SERIOUS
            add(
                "content/broken-image",
                severity,
                "Битая картинка",
                f"Картинка по адресу получила HTTP {status} — сервер отвечает ошибкой вместо изображения.",
                details={"src": url},
                help_url="https://developer.mozilla.org/en-US/docs/Web/HTML/Element/img",
            )


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
            ),
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

    _check_social_card(data, add)

    if not (data.get("canonical") or "").strip():
        add(
            "content/missing-canonical",
            Severity.MODERATE,
            "Нет canonical URL",
            "Поисковики решат сами, какую версию страницы считать основной; "
            "если нет <link rel=\"canonical\"> — риск дублей и размытия веса.",
            help_url="https://developers.google.com/search/docs/crawling-indexing/consolidate-duplicate-urls",
        )

    if not (data.get("ogSiteName") or "").strip():
        add(
            "content/missing-og-site-name",
            Severity.MODERATE,
            "Нет og:site_name",
            "В соцсетях и мессенджерах ссылка будет показываться без названия сайта — "
            "добавьте <meta property=\"og:site_name\"> в head.",
            help_url="https://ogp.me/#global",
        )

    if not data.get("jsonLdPresent"):
        add(
            "content/missing-structured-data",
            Severity.MODERATE,
            "Нет JSON-LD или структурированных данных",
            "Не добавлено структурированное описание страницы в коде (JSON-LD) — "
            "боты и поисковики не видят контакты, часы работы, услуги в коде, "
            "только визуально.",
            help_url="https://developers.google.com/search/docs/appearance/structured-data",
        )

    _check_broken_images(data, ctx, add)

    if not (data.get("viewport") or "").strip():
        add(
            "content/missing-viewport",
            Severity.SERIOUS,
            "Нет viewport meta",
            "Страница не адаптируется под мобильные экраны.",
            help_url="https://www.w3.org/WAI/WCAG22/Understanding/adapt-content-to-keyboard.html",
        )

    if not data.get("hasCharsetMeta"):
        add(
            "content/missing-charset",
            Severity.MODERATE,
            "Не указан charset страницы",
            "Без <meta charset> браузер угадывает кодировку — кириллица и другие не-ASCII символы ломаются.",
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
            "content/frame-title",
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
