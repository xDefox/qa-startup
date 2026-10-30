"""Краулер сайта: sitemap/robots, обход, группировка страниц по шаблонам.

Зачем группировка: на сайте 300 страниц, но шаблонов у них 8 (каталог, карточка,
главная, блог...). Проверять каждый шаблон — и проверять сотни однотипных страниц
бессмысленно. Отчёт для владельца сайта тоже должен быть про страницы-шаблоны,
а не про 300 URL.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urldefrag, urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx

from . import __version__
from .netguard import GuardedTransport

USER_AGENT = f"webscope/{__version__} (+https://github.com/webscope/webscope)"

_NON_HTML_SUFFIXES = (
    ".pdf",
    ".zip",
    ".rar",
    ".7z",
    ".gz",
    ".tar",
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".svg",
    ".webp",
    ".ico",
    ".bmp",
    ".tiff",
    ".css",
    ".js",
    ".mjs",
    ".map",
    ".mp4",
    ".webm",
    ".mov",
    ".avi",
    ".mkv",
    ".mp3",
    ".wav",
    ".ogg",
    ".flac",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".exe",
    ".dmg",
    ".iso",
    ".apk",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".rss",
    ".atom",
)

_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)
_HEX_RE = re.compile(r"^[0-9a-f]{16,}$", re.IGNORECASE)


@dataclass
class PageTarget:
    """Страница для сканирования."""

    url: str
    template: str
    depth: int
    title: str = ""
    description: str = ""

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "template": self.template,
            "depth": self.depth,
            "title": self.title,
            "description": self.description,
        }


@dataclass
class CrawlResult:
    """Результат обхода сайта."""

    root: str
    pages: list[PageTarget] = field(default_factory=list)
    templates: dict[str, list[str]] = field(default_factory=dict)
    skipped: list[dict] = field(default_factory=list)
    robots_checked: bool = False
    sitemap_used: bool = False

    def to_dict(self) -> dict:
        return {
            "root": self.root,
            "pages": [page.to_dict() for page in self.pages],
            "templates": self.templates,
            "skipped": self.skipped,
            "robots_checked": self.robots_checked,
            "sitemap_used": self.sitemap_used,
        }


class _LinkParser(HTMLParser):
    """Достаёт из HTML ссылки, title, meta description и ссылку на sitemap."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hrefs: list[str] = []
        self.sitemaps: list[str] = []
        self.title = ""
        self.description = ""
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key: (value or "") for key, value in attrs}
        if tag == "a" and attributes.get("href"):
            self.hrefs.append(attributes["href"])
        elif tag == "link" and "sitemap" in attributes.get("rel", "").lower() and attributes.get("href"):
            self.sitemaps.append(attributes["href"])
        elif tag == "title":
            self._in_title = True
        elif tag == "meta" and attributes.get("name", "").lower() == "description":
            self.description = attributes.get("content", "")

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data


def template_key(url: str) -> str:
    """Приводит URL к шаблону: динамические сегменты заменяются на плейсхолдеры.

    ``/catalog/12345`` и ``/catalog/67890`` → один шаблон ``/catalog/{id}``.
    """
    parsed = urlparse(url)
    segments: list[str] = []
    for segment in parsed.path.split("/"):
        if not segment:
            continue
        if segment.isdigit():
            segments.append("{id}")
        elif _UUID_RE.match(segment):
            segments.append("{uuid}")
        elif _HEX_RE.match(segment):
            segments.append("{hash}")
        else:
            segments.append(segment)
    path = "/" + "/".join(segments) if segments else "/"
    return f"{parsed.netloc}{path}"


def is_html_candidate(url: str) -> bool:
    """Отсекает заведомо не-HTML адреса (картинки, архивы, шрифты)."""
    path = urlparse(url).path.lower()
    return not path.endswith(_NON_HTML_SUFFIXES)


def extract_links(html: str, base_url: str) -> tuple[list[str], list[str]]:
    """Возвращает (ссылки, sitemap-ссылки) в абсолютном виде."""
    links, sitemaps, _title, _description = parse_page(html, base_url)
    return links, sitemaps


def squash_ws(text: str) -> str:
    """Схлопывает все пробельные символы (включая переводы строк) в один пробел."""
    return " ".join(text.split())


def parse_page(html: str, base_url: str) -> tuple[list[str], list[str], str, str]:
    """Возвращает (ссылки, sitemap-ссылки, title, description) из HTML страницы."""
    parser = _LinkParser()
    try:
        parser.feed(html)
    except Exception:  # noqa: BLE001 - битый HTML не должен ронять обход
        return [], [], "", ""
    links = []
    for href in parser.hrefs:
        absolute = urljoin(base_url, href)
        links.append(absolute)
    sitemaps = [urljoin(base_url, href) for href in parser.sitemaps]
    return links, sitemaps, squash_ws(parser.title), squash_ws(parser.description)


def _origin(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _fetch_robots(client: httpx.Client, origin: str) -> RobotFileParser | None:
    parser = RobotFileParser()
    parser.set_url(f"{origin}/robots.txt")
    try:
        response = client.get(f"{origin}/robots.txt")
        if response.status_code == 403:
            # RFC 9309: 403 — роботу отказано в доступе, считаем «запрещено всё».
            # У RobotFileParser disallow_all — флаг, а не метод.
            parser.disallow_all = True
            return parser
        if response.status_code == 401:
            # 401 — это не политика обхода, а требование представиться. Скрипт
            # умеет ходить под basic/form-авторизацией, поэтому не превращаем
            # закрытый стенд в «пустой сайт»: страница сама сообщит про 401.
            return None
        if response.status_code >= 400:
            return None
        parser.parse(response.text.splitlines())
        return parser
    except httpx.HTTPError:
        return None


def _parse_sitemap(text: str) -> tuple[list[str], list[str]]:
    """Разбирает sitemap.xml: возвращает (urls, urls_вложенных_sitemap)."""
    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return [], []

    namespace = ""
    if root.tag.startswith("{"):
        namespace = root.tag[: root.tag.index("}") + 1]

    tag = root.tag.replace(namespace, "")
    locs = [element.text.strip() for element in root.iter(f"{namespace}loc") if element.text]

    if tag == "sitemapindex":
        return [], locs
    return locs, []


def crawl(
    root_url: str,
    *,
    max_pages: int = 30,
    max_depth: int = 2,
    respect_robots: bool = True,
    timeout: float = 15.0,
    user_agent: str = USER_AGENT,
    headers: dict[str, str] | None = None,
    allow_private: bool = False,
) -> CrawlResult:
    """Обходит сайт и возвращает список страниц, сгруппированных по шаблонам.

    ``headers`` — дополнительные заголовки на все запросы: авторизация
    (``Authorization`` для basic-защиты или ``Cookie`` живой form-сессии).

    ``allow_private`` снимает SSRF-запрет (свои стенды и локальные файлы);
    по умолчанию каждый запрос, включая редиректы, проверяется на непубличный
    адрес (``netguard.GuardedTransport``).
    """
    root_url, _ = urldefrag(root_url)
    origin = _origin(root_url)
    result = CrawlResult(root=root_url)

    merged_headers = {"User-Agent": user_agent, **(headers or {})}
    transport = GuardedTransport(allow_private=allow_private)
    with httpx.Client(
        timeout=timeout,
        follow_redirects=True,
        headers=merged_headers,
        transport=transport,
    ) as client:
        robots = _fetch_robots(client, origin) if respect_robots else None
        result.robots_checked = robots is not None

        seeds: list[str] = []
        sitemap_urls: list[str] = []
        try:
            response = client.get(f"{origin}/sitemap.xml")
            if response.status_code < 400:
                urls, children = _parse_sitemap(response.text)
                seeds.extend(urls)
                sitemap_urls.extend(children)
                result.sitemap_used = bool(urls or children)
        except httpx.HTTPError:
            pass

        # Вложенные sitemap-индексы (обычно их несколько — по разделам).
        for child in sitemap_urls[:10]:
            try:
                child_response = client.get(child)
                if child_response.status_code < 400:
                    urls, _ = _parse_sitemap(child_response.text)
                    seeds.extend(urls)
            except httpx.HTTPError:
                continue

        # Главная страница — источник ссылок, если sitemap нет.
        homepage_loaded = False
        try:
            homepage = client.get(root_url)
            if homepage.status_code >= 400:
                result.skipped.append({"url": root_url, "reason": f"HTTP {homepage.status_code}"})
                homepage_html = ""
            else:
                homepage_html = homepage.text
                homepage_loaded = True
        except httpx.HTTPError as exc:
            result.skipped.append({"url": root_url, "reason": f"не удалось загрузить: {exc}"})
            homepage_html = ""

        _, sitemap_links, _, _ = parse_page(homepage_html, root_url)
        for sitemap_link in sitemap_links[:3]:
            try:
                link_response = client.get(sitemap_link)
                if link_response.status_code < 400:
                    urls, _ = _parse_sitemap(link_response.text)
                    seeds.extend(urls)
                    result.sitemap_used = True
            except httpx.HTTPError:
                continue

        seeds.append(root_url)
        candidates = [seed for seed in seeds if urlparse(seed).netloc == urlparse(root_url).netloc]
        seeds = candidates or [root_url]

        visited: dict[str, PageTarget] = {}
        # depth=0 — только стартовая страница: её HTML уже загружен. URL из
        # sitemap обязаны скачиваться сами, иначе им достаётся title главной
        # и проверка дублей по шаблонам даёт ложные срабатывания на всём сайте.
        queue: list[tuple[str, int]] = [(seed, 0 if seed == root_url else 1) for seed in dict.fromkeys(seeds)]

        while queue and len(visited) < max_pages:
            url, depth = queue.pop(0)
            url, _ = urldefrag(url)
            if url in visited:
                continue
            if not is_html_candidate(url):
                result.skipped.append({"url": url, "reason": "не HTML-страница"})
                continue
            if robots is not None and not robots.can_fetch(user_agent, url):
                result.skipped.append({"url": url, "reason": "запрещено robots.txt"})
                continue

            if depth > 0:
                try:
                    response = client.get(url)
                    if response.status_code >= 400:
                        result.skipped.append({"url": url, "reason": f"HTTP {response.status_code}"})
                        continue
                    html = response.text
                except httpx.HTTPError as exc:
                    result.skipped.append({"url": url, "reason": f"ошибка загрузки: {exc}"})
                    continue
            elif url == root_url and not homepage_loaded:
                # Главную уже пробовали загрузить выше — второй раз не стучимся,
                # но и «страницу» с пустым title в обход не добавляем.
                continue
            else:
                html = homepage_html

            # title/description из сырых HTML — для проверки дублей по шаблонам
            _links, _sitemaps, page_title, page_description = parse_page(html, url)
            visited[url] = PageTarget(
                url=url,
                template=template_key(url),
                depth=depth,
                title=page_title,
                description=page_description,
            )

            if depth >= max_depth:
                continue

            links = _links
            for link in links:
                parsed = urlparse(link)
                if parsed.scheme not in {"http", "https"}:
                    continue
                if parsed.netloc != urlparse(root_url).netloc:
                    continue
                if link not in visited:
                    queue.append((link, depth + 1))

    pages = sorted(visited.values(), key=lambda page: (page.depth, page.url))
    result.pages = pages
    templates: dict[str, list[str]] = {}
    for page in pages:
        templates.setdefault(page.template, []).append(page.url)
    result.templates = templates
    return result


def representative_pages(crawl_result: CrawlResult, *, all_pages: bool = False) -> list[PageTarget]:
    """По одной странице на шаблон (или все страницы, если нужно)."""
    if all_pages:
        return list(crawl_result.pages)
    chosen: list[PageTarget] = []
    seen_templates: set[str] = set()
    for page in crawl_result.pages:
        if page.template in seen_templates:
            continue
        seen_templates.add(page.template)
        chosen.append(page)
    return chosen
