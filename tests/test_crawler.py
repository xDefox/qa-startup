"""Тесты краулера: шаблоны, robots, разбор ссылок."""

from __future__ import annotations

from webscope.crawler import extract_links, is_html_candidate, template_key


def test_template_key_replaces_numeric_ids() -> None:
    assert template_key("https://site.com/catalog/12345") == template_key("https://site.com/catalog/67890")
    assert template_key("https://site.com/catalog/12345") == "site.com/catalog/{id}"


def test_template_key_replaces_uuid() -> None:
    first = template_key("https://site.com/p/2f1c9d80-1111-2222-3333-444455556666")
    second = template_key("https://site.com/p/9a8b7c60-9999-8888-7777-666655554444")
    assert first == second
    assert "{uuid}" in first


def test_template_key_keeps_static_paths() -> None:
    assert template_key("https://site.com/about/team") == "site.com/about/team"
    assert template_key("https://site.com/") == "site.com/"


def test_is_html_candidate_filters_binaries() -> None:
    assert is_html_candidate("https://site.com/about") is True
    assert is_html_candidate("https://site.com/logo.png") is False
    assert is_html_candidate("https://site.com/file.pdf") is False


def test_extract_links_resolves_relative() -> None:
    html = '<a href="/about">About</a><a href="https://other.com/x">Other</a><link rel="sitemap" href="/sitemap.xml">'
    links, sitemaps = extract_links(html, "https://site.com/")
    assert "https://site.com/about" in links
    assert "https://other.com/x" in links
    assert sitemaps == ["https://site.com/sitemap.xml"]


def test_extract_links_survives_broken_html() -> None:
    links, sitemaps = extract_links("<a href=", "https://site.com/")
    assert links == []
    assert sitemaps == []
