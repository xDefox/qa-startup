"""Кому принадлежит ресурс: сайту или чужому виджету."""

from __future__ import annotations

from webscope.origins import is_external, registrable_domain, resource_owner


def test_registrable_domain() -> None:
    assert registrable_domain("www.varkacoffee.by") == "varkacoffee.by"
    assert registrable_domain("mdd.yandex.net") == "yandex.net"
    assert registrable_domain("static.tildacdn.biz") == "tildacdn.biz"
    assert registrable_domain("shop.example.co.uk") == "example.co.uk"
    assert registrable_domain("localhost") == "localhost"


def test_same_site_subdomains_are_own() -> None:
    page = "https://varkacoffee.by/menu"
    assert resource_owner("https://static.varkacoffee.by/a.png", page) == "site"
    assert not is_external("https://static.varkacoffee.by/a.png", page)


def test_widgets_are_third_party() -> None:
    page = "https://varkacoffee.by/"
    assert resource_owner("https://mdd.yandex.net/", page) == "third-party"
    assert resource_owner("https://prebid.admatic.com.tr/setuid", page) == "third-party"
    assert is_external("https://mc.yandex.ru/metrika/tag.js", page)
