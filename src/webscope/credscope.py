"""Область действия учётных данных сайта: секреты не уходят чужим хостам.

Библиотеки по умолчанию шлют заголовки авторизации на все запросы сессии:
``extra_http_headers`` Playwright и ``headers`` httpx-клиента доходят и до
CDN, и до шрифтов чужих доменов, и до чужих sitemap — стоит сайту лишь
сослаться на внешний ресурс. Утечка молчаливая: пароль в base64 уезжает
туда, где ему делать нечего, просто потому что заголовок «для всего
клиента».

Инструменты отсюда держат секреты на хостах самого сайта:

* ``auth_origins`` — origin'ы для браузерных ``http_credentials``: движок
  отвечает на 401-челлендж только совпавшему origin, чужому хосту — «нет»;
* ``strip_out_of_scope_headers`` — httpx event hook, снимающий
  ``Authorization``/``Cookie`` с запросов чужим хостам, включая прыжки
  редиректов;
* ``scoped_cookie_header`` — плоская строка Cookie из браузерных cookies
  только своих доменов.

Правило «свой хост» — точное совпадение, поддомены корня и родительский
домен (apex↔www, cookie на ``.vstu.by`` при корне ``student.vstu.by``).
Чужой SSO-поддомен (``auth.vstu.by`` для корня ``student.vstu.by``) в
область не входит: браузер не стал бы слать его куки основному хосту, и мы
не шлём.
"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

import httpx

# Секреты, которые не должны уходить чужим хостам. Остальные заголовки
# (user-agent, accept) на чужом хосте терять не нужно — трогаем только своё.
CRED_HEADERS = ("authorization", "cookie")


def in_scope(host: str | None, root_url: str) -> bool:
    """Принадлежит ли хост сайту: корень, его поддомен или родительский домен.

    ``www.site.by`` и ``site.by`` — один сайт (редиректы между ними), cookie
    с доменом ``.vstu.by`` — своя для корня ``student.vstu.by``.
    """
    if not host:
        return False
    root_host = (urlsplit(root_url).hostname or "").lower()
    host = host.lower().rstrip(".")
    if not root_host or not host:
        return False
    if host == root_host or host.endswith(f".{root_host}"):
        return True
    # родительский домен: от корня отрезаем одну метку; TLD (".by") доменом
    # не считаем — сравниваем строго с получившимся родителем
    parent = root_host.split(".", 1)[1] if "." in root_host else ""
    return bool(parent) and host == parent


def auth_origins(root_url: str) -> list[str]:
    """Origin'ы сайта, куда браузеру разрешено шлёт basic-креды.

    Браузер посылает Authorization только совпавшему origin
    (``scheme://host:port``), а сайты часто живут на паре www↔apex с
    редиректом между ними: без второго origin половина страниц осталась бы
    за 401. IP-адресу двойник не придумываем.
    """
    parts = urlsplit(root_url)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        return []
    default_port = 80 if parts.scheme == "http" else 443
    port = f":{parts.port}" if parts.port and parts.port != default_port else ""
    host = parts.hostname.lower()
    origin = f"{parts.scheme}://{host}{port}"
    try:
        ipaddress.ip_address(host)
        return [origin]
    except ValueError:
        pass
    bare = host[4:] if host.startswith("www.") else f"www.{host}"
    return [origin, f"{parts.scheme}://{bare}{port}"]


def strip_out_of_scope_headers(root_url: str):
    """httpx event hook: снимает Authorization/Cookie с чужих хостов.

    Краулер ходит одним клиентом по всему, что найдёт: sitemap-индексы и
    ссылки на sitemap с чужих хостов, редиректы. Хук срабатывает на каждый
    запрос отдельно — и на прыжок редиректа, — поэтому секрет не уходит за
    пределы сайта даже косвенным путём.
    """

    def hook(request: httpx.Request) -> None:
        if in_scope(request.url.host, root_url):
            return
        for name in CRED_HEADERS:
            if name in request.headers:
                del request.headers[name]

    return hook


def scoped_cookie_header(cookies: list[dict], root_url: str) -> str | None:
    """Плоский заголовок Cookie из браузерных cookies — только своих доменов.

    ``context.cookies()`` возвращает куки всех хостов сессии (страница входа
    спокойно подгружает третьи стороны), а краулеру доступна одна плоская
    строка: слепая склейка отправила бы чужие куки нашему же серверу.
    Браузер отбирал бы куки по домену — здесь то же самое.
    """
    parts = [
        f"{cookie['name']}={cookie['value']}"
        for cookie in cookies
        if in_scope((cookie.get("domain") or "").lstrip("."), root_url)
    ]
    return "; ".join(parts) if parts else None
