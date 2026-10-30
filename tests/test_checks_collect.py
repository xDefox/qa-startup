"""Сборщик данных для content-проверок: чего он не должен выкидывать.

Сам сборщик исполняется в браузере, его поведение проверяют
`tests/test_checks.py` (маркер `browser`). Здесь — дешёвая страховка на
выпавшие фильтры: такую потерю не видно ни в отчёте, ни в юнит-тестах,
потому что проверка просто перестаёт находить находки.

Именно так и пропали ссылки на эту же страницу: фильтр
`!href.startsWith('#')` убирал из `content/empty-link-name` все якорные
ссылки, и `<a href="#"></a>` перестала считаться дефектом. Браузерные тесты
ловили это сразу, но джоба `test-browser` падала ещё на сборке (не хватало
extra `web`), поэтому регрессия жила незамеченной.
"""

from __future__ import annotations

from webscope.checks import content


def _chain(name: str) -> str:
    """Вырезать из COLLECT объявление массива `name` вместе с фильтрами."""
    lines = content.COLLECT.splitlines()
    start = next(
        (i for i, line in enumerate(lines) if line.strip().startswith(f"const {name} = ")),
        None,
    )
    assert start is not None, f"в COLLECT нет {name}"
    chain: list[str] = []
    for line in lines[start:]:
        chain.append(line.strip())
        if line.rstrip().endswith(";"):
            break
    return " ".join(chain)


def _normalized(text: str) -> str:
    return text.replace('"', "'").replace(" ", "")


def test_empty_links_are_named_by_accessible_name() -> None:
    """Имя ссылки берётся из accessibleName, а не из text()."""
    assert "accessibleName" in _chain("emptyLinks")


def test_empty_links_include_in_page_anchors() -> None:
    """Ссылки на эту же страницу (href="#...") проверяются наравне с остальными."""
    chain = _normalized(_chain("emptyLinks"))
    assert "startsWith('#')" not in chain


def test_empty_buttons_do_not_repeat_link_findings() -> None:
    """Один дефект — одна находка: <a href> не попадает ещё и в кнопки."""
    chain = _normalized(_chain("emptyButtons"))
    assert "tagName==='A'" in chain
    assert "hasAttribute('href')" in chain
    assert "closest('form')" in chain
