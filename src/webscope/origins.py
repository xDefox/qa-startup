"""Чьи ресурсы сломались: сайта или чужих виджетов.

На любом живом сайте часть запросов уходит на сторонние домены: счётчики
аналитики, карты, SDK рекламы, пиксели соцсетей. Их ошибки и блокировки
(особенно при включённом блокировщике или на сервере за пределами нашей
сети) — не дефект сайта: владельцу нечего исправлять. Такие находки
помечаются отдельно, чтобы в отчёте и балл они не шли как проблемы сайта.
"""

from __future__ import annotations

from urllib.parse import urlparse

TRACKING = "tracking"
THIRD_PARTY = "third-party"
SITE = "site"


def registrable_domain(host: str) -> str:
    """Грубое «имя сайта»: последние две метки хоста.

    Полноценный PSL здесь не нужен: он тянет зависимость и данные, а для
    отсечения чужих виджетов достаточно ``www.yandex.ru`` → ``yandex.ru``.
    Исключения из двух меток (co.uk, com.tr) собираются вручную — их мало.
    """
    host = (host or "").strip().lower().rstrip(".")
    if not host:
        return ""
    labels = host.split(".")
    if len(labels) <= 2:
        return host
    two_level = {"co", "com", "org", "net", "ac", "gov", "edu"}
    if labels[-2] in two_level and len(labels[-1]) == 2:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def host_of(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


def resource_owner(resource_url: str, page_url: str) -> str:
    """Кому принадлежит ресурс: сайту, стороннему домену или трекеру."""
    resource_host = host_of(resource_url)
    page_host = host_of(page_url)
    if not resource_host:
        return SITE
    if registrable_domain(resource_host) == registrable_domain(page_host):
        return SITE
    return THIRD_PARTY


def is_external(resource_url: str, page_url: str) -> bool:
    """Ресурс с чужого домена (включая трекеры) — не дефект сайта."""
    return resource_owner(resource_url, page_url) != SITE
