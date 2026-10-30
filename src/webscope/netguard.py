"""Сетевые ограничения: что сканеру можно открывать.

SSRF-защита проверяет не только стартовый адрес, но и каждый запрос, который
делает браузер или HTTP-клиент: редирект публичного сайта на `169.254.169.254`
и подгрузка картинки с `http://127.0.0.1:9200` — такие же способы дотянуться
до внутренней сети, как и прямой ввод приватного URL.

Модуль намеренно не знает ни про Playwright, ни про остальной движок: здесь
только проверка адресов и httpx-транспорт, который её применяет.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

import httpx

# Атрибуты ipaddress, при которых адрес считается непубличным.
_FORBIDDEN_ATTRS = (
    "is_private",
    "is_loopback",
    "is_link_local",
    "is_reserved",
    "is_multicast",
    "is_unspecified",
)

_ALLOWED_SCHEMES = {"http", "https"}


def is_forbidden_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Непубличный адрес: приватный, loopback, link-local, служебный."""
    return any(getattr(address, attribute) for attribute in _FORBIDDEN_ATTRS)


def parse_ip(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """IP-адрес из хоста (IPv6 может прийти с zone-id: ``fe80::1%eth0``)."""
    try:
        return ipaddress.ip_address((host or "").split("%", 1)[0])
    except ValueError:
        return None


def host_resolves_to_private(host: str, cache: dict[str, bool] | None = None) -> bool:
    """Ведёт ли хост на непубличный адрес.

    Нерезолвящийся хост тоже считается закрытым: запрос всё равно не пройдёт,
    а пропускать его — значит оставить окно для DNS rebinding.
    """
    key = (host or "").strip().lower()
    if cache is not None and key in cache:
        return cache[key]

    blocked = True
    try:
        infos = socket.getaddrinfo(key, None)
    except (socket.gaierror, UnicodeError, OSError):
        blocked = True
    else:
        blocked = False
        for info in infos:
            address = parse_ip(info[4][0])
            if address is None or is_forbidden_address(address):
                blocked = True
                break

    if cache is not None:
        cache[key] = blocked
    return blocked


def url_targets_private_network(url: str, cache: dict[str, bool] | None = None) -> bool:
    """Ведёт ли URL (http/https) на непубличный адрес. Прочие схемы — не сеть."""
    parsed = urlparse(url)
    if parsed.scheme not in _ALLOWED_SCHEMES:
        return False
    host = parsed.hostname
    if not host:
        return False
    address = parse_ip(host)
    if address is not None:
        return is_forbidden_address(address)
    return host_resolves_to_private(host, cache)


class GuardedTransport(httpx.BaseTransport):
    """httpx-транспорт, который не пускает запросы на непубличные адреса.

    Проверка идёт на каждый запрос транспорта, поэтому редирект
    `https://site.com → http://192.168.1.1/` обрывается до соединения.
    """

    def __init__(self, *, allow_private: bool = False, inner: httpx.BaseTransport | None = None) -> None:
        self.allow_private = allow_private
        self._inner = inner if inner is not None else httpx.HTTPTransport()
        self._cache: dict[str, bool] = {}

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if not self.allow_private:
            host = request.url.host or ""
            if url_targets_private_network(str(request.url), self._cache):
                raise httpx.ConnectError(f"Заблокирован запрос к непубличному адресу {host}", request=request)
        return self._inner.handle_request(request)

    def close(self) -> None:
        self._inner.close()
