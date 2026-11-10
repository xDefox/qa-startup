"""Watchdog — детектор изменений для инкрементальных проверок.

Отвечает за:
- Вычисление контент-хешей страниц (HTML + CSS + JS)
- Отслеживание ETag / Last-Modified заголовков
- Парсинг sitemap.xml для lastmod
- Сравнение с предыдущими снимками для определения изменённых URL
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from urllib.parse import urljoin, urlparse

if TYPE_CHECKING:
    from playwright.sync_api import Page

from webscope.models import ScanResult
from webscope.webapp.storage import Storage

LOGGER = logging.getLogger("webscope.watchdog")


@dataclass
class PageSnapshot:
    """Снимок состояния одной страницы."""
    url: str
    content_hash: str
    etag: str | None = None
    last_modified: str | None = None
    status_code: int = 200
    fetched_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


@dataclass
class SiteSnapshot:
    """Полный снимок сайта для сравнения."""
    site_id: int
    url: str
    pages: dict[str, PageSnapshot] = field(default_factory=dict)
    sitemap_urls: list[str] = field(default_factory=list)
    fetched_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict:
        return {
            "site_id": self.site_id,
            "url": self.url,
            "pages": {url: {
                "content_hash": p.content_hash,
                "etag": p.etag,
                "last_modified": p.last_modified,
                "status_code": p.status_code,
                "fetched_at": p.fetched_at,
            } for url, p in self.pages.items()},
            "sitemap_urls": self.sitemap_urls,
            "fetched_at": self.fetched_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SiteSnapshot":
        pages = {}
        for url, p in data.get("pages", {}).items():
            pages[url] = PageSnapshot(
                url=url,
                content_hash=p["content_hash"],
                etag=p.get("etag"),
                last_modified=p.get("last_modified"),
                status_code=p.get("status_code", 200),
                fetched_at=p.get("fetched_at", ""),
            )
        return cls(
            site_id=data["site_id"],
            url=data["url"],
            pages=pages,
            sitemap_urls=data.get("sitemap_urls", []),
            fetched_at=data.get("fetched_at", ""),
        )


class ChangeDetector:
    """Детектор изменений для инкрементальных проверок."""

    def __init__(self, storage: Storage):
        self.storage = storage

    def compute_content_hash(self, html: str, css_urls: list[str], js_urls: list[str]) -> str:
        """Вычисляет хеш контента: HTML + подключаемые CSS/JS.
        
        Для полноты можно скачивать CSS/JS, но для скорости хешируем только HTML
        и URLs подключаемых ресурсов.
        """
        content = html
        # Добавляем URLs ресурсов в хеш (порядок важен)
        for url in sorted(css_urls):
            content += f"\n<!-- CSS: {url} -->"
        for url in sorted(js_urls):
            content += f"\n<!-- JS: {url} -->"
        return hashlib.sha256(content.encode("utf-8")).hexdigest()[:32]

    def extract_resources(self, page: "Page", base_url: str) -> tuple[list[str], list[str]]:
        """Извлекает URLs CSS и JS со страницы."""
        css_urls = []
        js_urls = []
        
        # CSS: <link rel="stylesheet"> и @import в style
        for link in page.query_selector_all("link[rel='stylesheet']"):
            href = link.get_attribute("href")
            if href:
                css_urls.append(self._resolve_url(href, base_url))
        
        for style in page.query_selector_all("style"):
            content = style.inner_text()
            for match in re.finditer(r'@import\s+["\']([^"\']+)["\']', content):
                css_urls.append(self._resolve_url(match.group(1), base_url))
        
        # JS: <script src>
        for script in page.query_selector_all("script[src]"):
            src = script.get_attribute("src")
            if src:
                js_urls.append(self._resolve_url(src, base_url))
        
        return css_urls, js_urls

    def _resolve_url(self, url: str, base: str) -> str:
        """Приводит URL к абсолютному виду."""
        if url.startswith(("http://", "https://", "//")):
            return url if url.startswith("http") else "https:" + url
        return urljoin(base, url)

    def fetch_page_snapshot(self, page: "Page", url: str) -> PageSnapshot:
        """Создаёт снимок страницы: хеш контента + заголовки."""
        html = page.content()
        
        # Извлекаем ресурсы
        css_urls, js_urls = self.extract_resources(page, url)
        
        # Хеш контента
        content_hash = self.compute_content_hash(page.content(), [], [])
        # Для простоты хешируем только HTML; CSS/JS URLs можно добавить позже
        content_hash = hashlib.sha256(page.content().encode("utf-8")).hexdigest()[:32]
        
        # Заголовки ответа (если доступны)
        response = page._last_response if hasattr(page, "_last_response") else None
        etag = response.headers.get("etag") if response else None
        last_modified = response.headers.get("last-modified") if response else None
        status_code = response.status if response else 200
        
        return PageSnapshot(
            url=url,
            content_hash=content_hash,
            etag=etag,
            last_modified=last_modified,
            status_code=status_code,
        )

    def detect_changes(self, site_id: int, current_pages: dict[str, PageSnapshot]) -> tuple[list[str], list[str], list[str]]:
        """Сравнивает текущие страницы с сохранённым снимком.
        
        Returns:
            (added_urls, changed_urls, removed_urls)
        """
        # Получаем сохранённый снимок
        stored = self.storage.get_site_snapshot(site_id)
        if not stored:
            # Первый запуск — все страницы новые
            return list(current_pages.keys()), [], []
        
        # stored is a dict from JSON, not a SiteSnapshot object
        old_pages = stored.get("pages", {})
        current_urls = set(current_pages.keys())
        old_urls = set(old_pages.keys())
        
        added = list(current_urls - old_urls)
        removed = list(old_urls - current_urls)
        
        changed = []
        for url in current_urls & old_urls:
            old_snap = old_pages[url]
            new_snap = current_pages[url]
            
            # Сравниваем по приоритету: content_hash > etag > last_modified
            if new_snap.content_hash != old_snap.get("content_hash", ""):
                changed.append(url)
            elif new_snap.etag and old_snap.get("etag") and new_snap.etag != old_snap.get("etag"):
                changed.append(url)
            elif new_snap.last_modified and old_snap.get("last_modified") and new_snap.last_modified != old_snap.get("last_modified"):
                changed.append(url)
            elif new_snap.status_code != old_snap.get("status_code", 200):
                changed.append(url)
        
        return added, changed, removed

    def fetch_sitemap_urls(self, page: "Page", base_url: str) -> list[str]:
        """Парсит sitemap.xml для получения URL и lastmod."""
        urls = []
        try:
            # Пробуем стандартные пути sitemap
            sitemap_urls = [
                urljoin(url, "/sitemap.xml"),
                urljoin(url, "/sitemap_index.xml"),
                urljoin(url, "/sitemap.xml.gz"),
            ]
            
            for sitemap_url in sitemap_urls:
                try:
                    # TODO: скачать и распарсить sitemap
                    # Пока заглушка
                    pass
                except Exception:
                    continue
        except Exception as e:
            LOGGER.warning("Failed to fetch sitemap for %s: %s", base_url, e)
        return urls

    def save_snapshot(self, site_id: int, url: str, pages: dict[str, PageSnapshot], sitemap_urls: list[str] | None = None) -> None:
        """Сохраняет снимок сайта в хранилище."""
        snapshot = SiteSnapshot(
            site_id=site_id,
            url=url,
            pages=pages,
            sitemap_urls=sitemap_urls or [],
        )
        # Сохраняем в БД (JSON в отдельной таблице или в sites таблице)
        # TODO: реализовать сохранение в Storage
        pass


# Вспомогательные функции для интеграции с Monitor

async def detect_changed_urls(storage: Storage, site_id: int, page: "Page", base_url: str) -> list[str]:
    """Высокоуровневая функция: получает изменённые URL для сайта."""
    detector = ChangeDetector(storage)
    
    # Собираем снимки текущих страниц
    current_pages = {}
    # TODO: обойти страницы сайта и собрать снимки
    # Пока заглушка — возвращаем пустой список
    return []


def update_site_snapshot(storage: Storage, site_id: int, url: str, pages: dict) -> None:
    """Сохраняет обновлённый снимок сайта."""
    # TODO: реализовать
    pass