"""Тесты краулера: шаблоны, robots, разбор ссылок."""

from __future__ import annotations

from webscope.crawler import CrawlResult, PageTarget, extract_links, is_html_candidate, parse_page, template_key


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


def test_parse_page_extracts_title_and_description() -> None:
    html = """<html><head><title>Товар — Магазин</title>
    <meta name="description" content="Классный товар"></head><body></body></html>"""
    links, sitemaps, title, description = parse_page(html, "https://site.com/")
    assert title == "Товар — Магазин"
    assert description == "Классный товар"
    assert links == []
    assert sitemaps == []


def test_parse_page_normalizes_whitespace_in_title() -> None:
    html = "<html><head><title>\n  Каталог\n\n товаров </title></head></html>"
    _, _, title, _ = parse_page(html, "https://site.com/")
    assert title == "Каталог товаров"


def test_parse_page_handles_missing_title_and_description() -> None:
    _, _, title, description = parse_page("<html><body>просто текст</body></html>", "https://site.com/")
    assert title == ""
    assert description == ""


def test_parse_page_survives_broken_html() -> None:
    _, _, title, _description = parse_page("<title>", "https://site.com/")
    assert title == "" or isinstance(title, str)


def _dup_pages() -> CrawlResult:
    pages = [
        PageTarget("https://s.com/catalog/1", "s.com/catalog/{id}", 1, title="Каталог", description="Все товары"),
        PageTarget("https://s.com/catalog/2", "s.com/catalog/{id}", 1, title="Каталог", description="Все товары"),
        PageTarget("https://s.com/catalog/3", "s.com/catalog/{id}", 1, title="Каталог", description="Все товары"),
        PageTarget("https://s.com/", "s.com/", 0, title="Главная", description="Все товары"),
    ]
    return CrawlResult(
        root="https://s.com/",
        pages=pages,
        templates={"s.com/catalog/{id}": [p.url for p in pages[:3]], "s.com/": [pages[3].url]},
    )


def test_duplicate_meta_detects_same_title_and_description() -> None:
    from webscope.scanner import _duplicate_meta_findings

    findings = _duplicate_meta_findings(_dup_pages())
    rules = {f.rule for f in findings}
    assert rules == {"content/duplicate-title", "content/duplicate-description"}


def test_duplicate_meta_groups_within_one_template() -> None:
    from webscope.scanner import _duplicate_meta_findings

    findings = _duplicate_meta_findings(_dup_pages())
    title = next(f for f in findings if f.rule == "content/duplicate-title")
    # нашли три дубля каталога, но не главную, у которой другой шаблон
    assert title.details["count"] == 3
    assert title.details["template"] == "s.com/catalog/{id}"
    assert "s.com/" not in title.details["examples"]


def test_duplicate_meta_ignores_unique_pages() -> None:
    from webscope.scanner import _duplicate_meta_findings

    pages = [
        PageTarget("https://s.com/p/1", "s.com/p/{id}", 1, title="Товар 1", description="Первый"),
        PageTarget("https://s.com/p/2", "s.com/p/{id}", 1, title="Товар 2", description="Второй"),
    ]
    result = CrawlResult(root="https://s.com/", pages=pages, templates={"s.com/p/{id}": [p.url for p in pages]})
    assert _duplicate_meta_findings(result) == []


def test_duplicate_meta_ignores_pages_without_title() -> None:
    from webscope.scanner import _duplicate_meta_findings

    pages = [
        PageTarget("https://s.com/a", "s.com/a", 1, title="", description=""),
        PageTarget("https://s.com/b", "s.com/b", 1, title="", description=""),
    ]
    result = CrawlResult(
        root="https://s.com/", pages=pages, templates={"s.com/a": ["https://s.com/a"], "s.com/b": ["https://s.com/b"]}
    )
    assert _duplicate_meta_findings(result) == []


def test_duplicate_meta_treats_whitespace_and_case_as_equal() -> None:
    from webscope.scanner import _duplicate_meta_findings

    pages = [
        PageTarget("https://s.com/x/1", "s.com/x/{id}", 1, title="  Каталог  ", description=""),
        PageTarget("https://s.com/x/2", "s.com/x/{id}", 1, title="каталог", description=""),
    ]
    result = CrawlResult(root="https://s.com/", pages=pages, templates={"s.com/x/{id}": [p.url for p in pages]})
    findings = _duplicate_meta_findings(result)
    assert [f.rule for f in findings] == ["content/duplicate-title"]
