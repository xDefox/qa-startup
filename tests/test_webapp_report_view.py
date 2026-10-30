"""Страница отчёта: все находки в одной таблице и все три категории.

Категории: дефекты сайта по серьёзности (критично/существенно/желательно/мелочи)
и отдельная группа «замечания сканирования» — ошибки чужих виджетов.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from webscope.models import Finding, ScanResult, Severity
from webscope.webapp.app import EXTERNAL_TITLE, create_app
from webscope.webapp.storage import Storage


def _finding(rule: str, severity: Severity, **details) -> Finding:
    return Finding(
        rule=rule,
        severity=severity,
        title=rule,
        message="",
        url="https://example.com/",
        source="webscope.test",
        details=details,
    )


@pytest.fixture()
def client(tmp_path: Path):
    from fastapi.testclient import TestClient

    storage = Storage(tmp_path / "test.db")
    site = storage.add_site("https://example.com", email=None, telegram_chat=None, schedule="off")
    run = storage.start_run(site.id)
    storage.finish_run(
        run.id,
        ScanResult(
            url="https://example.com",
            final_url="https://example.com/",
            pages_scanned=1,
            duration_ms=100,
            findings=[
                _finding("content/no-h1", Severity.MODERATE),
                _finding("links/target-blank-noopener", Severity.MINOR),
                _finding("content/missing-description", Severity.MINOR),
                _finding(
                    "console/failed-request",
                    Severity.MODERATE,
                    resource="https://mdd.yandex.net/",
                    owner="third-party",
                ),
            ],
        ),
    )
    app = create_app(db_path=tmp_path / "test.db")
    with TestClient(app) as test_client:
        yield test_client, site


def test_report_table_has_all_findings_and_three_categories(client) -> None:
    test_client, site = client
    html = test_client.get(f"/sites/{site.id}").text

    # Таблица одна, а не отдельный список для «серьёзных» находок.
    assert html.count('class="findings-table"') == 1
    assert 'id="findings-table"' not in html

    # Переключатель — иконки без текста, в стиле кнопки темы.
    # Рядом с ним такая же иконка «сохранить отчёт» (стрелка вниз).
    assert html.count('class="view-btn"') == 2
    assert html.count('class="view-btn download-btn"') == 1
    assert "☰" not in html and "⊞" not in html
    assert 'aria-label="Списком"' in html and 'aria-label="Таблицей"' in html
    assert 'aria-label="Сохранить отчёт"' in html

    # Все три категории присутствуют: мелочи, желательно и чужие виджеты.
    assert "Мелочи — на ваше усмотрение" in html
    assert "Желательно — стоит поправить" in html
    assert EXTERNAL_TITLE in html

    # Строки таблицы включают находку из чужих виджетов и мелочь.
    assert "content/missing-description" in html
    assert "console/failed-request" in html
    assert "mdd.yandex.net" in html

    # Счётчик: проблемы сайта и отдельно виджеты.
    assert "Все находки (3)" in html
    assert "в чужих виджетах: 1" in html


def test_table_contains_minor_findings(client) -> None:
    """Раньше мелочи выпадали из таблицы (фильтр key != 'minor')."""
    test_client, site = client
    html = test_client.get(f"/sites/{site.id}").text
    table = html[html.index('class="findings-table"') : html.index("</table>")]
    assert "content/missing-description" in table
    assert "console/failed-request" in table


def test_all_report_formats_are_served(client) -> None:
    """Все форматы отчёта отдаются, включая SARIF.

    Регресс: ``report.sarif`` падал с 500 — модуль ``json`` не был импортирован.
    """
    test_client, site = client
    for fmt in ("html", "json", "txt", "xml", "sarif"):
        response = test_client.get(f"/api/sites/{site.id}/report.{fmt}")
        assert response.status_code == 200, fmt
    assert "runs" in test_client.get(f"/api/sites/{site.id}/report.sarif").json()


@pytest.mark.parametrize("fmt", ["html", "json", "txt", "xml", "sarif"])
def test_report_download_is_a_file(client, fmt: str) -> None:
    """Кнопка «скачать» отдаёт файл, а не открывает отчёт в браузере."""
    test_client, site = client
    response = test_client.get(f"/api/sites/{site.id}/report.{fmt}?download=1")
    assert response.status_code == 200
    disposition = response.headers["content-disposition"]
    assert disposition.startswith("attachment;")
    assert 'filename="webscope-example.com-' in disposition
    assert disposition.rstrip('"').endswith(f".{fmt}")
    assert "no-store" in response.headers["cache-control"]


@pytest.mark.parametrize("fmt", ["html", "json", "txt", "xml", "sarif"])
def test_report_without_download_stays_inline(client, fmt: str) -> None:
    """Обычный адрес по-прежнему показывает отчёт, ничего не навязывая скачивать."""
    test_client, site = client
    response = test_client.get(f"/api/sites/{site.id}/report.{fmt}")
    assert response.status_code == 200
    assert "content-disposition" not in response.headers


def _download_modal(html: str) -> str:
    """Кусок разметки модалки «Сохранить отчёт»."""
    start = html.index('class="download-modal"')
    return html[start : html.index("</dialog>", start)]


def test_download_is_available_from_site_page(client) -> None:
    test_client, site = client
    page = test_client.get(f"/sites/{site.id}")
    assert page.status_code == 200
    assert '<dialog class="download-modal" id="download-modal"' in page.text
    assert "Сохранить отчёт" in page.text
    for fmt in ("html", "json", "txt", "xml", "sarif"):
        assert f"/api/sites/{site.id}/report.{fmt}?download=1" in page.text


def test_download_trigger_sits_next_to_view_toggle(client) -> None:
    """Сохранение — в шапке находок, рядом с переключателем «списком/таблицей».

    Один ряд иконок над находками: сначала «как показать», потом «сохранить».
    Раньше кнопки форматов стояли в шапке страницы и спорили с «Проверить ещё раз»,
    а отдельная карточка в конце заставляла листать весь отчёт.
    """
    test_client, site = client
    html = test_client.get(f"/sites/{site.id}").text
    head = html.index('class="findings-head"')
    toggle = html.index('class="view-toggle"', head)
    trigger = html.index('id="download-open"', head)
    table = html.index('class="findings-table"', head)
    assert head < toggle < trigger < table, "кнопка сохранения — в шапке, сразу за переключателем вида"
    assert trigger > html.index("Проверить ещё раз"), "и ниже шапки страницы"


def test_download_formats_live_in_a_modal(client) -> None:
    """Форматы — в <dialog>, а не в выпадашке: меню поверх отчёта закрывало таблицу."""
    test_client, site = client
    html = test_client.get(f"/sites/{site.id}").text
    modal = _download_modal(html)
    assert modal.startswith('class="download-modal" id="download-modal"')
    assert 'aria-labelledby="download-modal-title"' in modal
    assert '<h2 id="download-modal-title">Сохранить отчёт</h2>' in modal
    assert modal.count('class="download-option"') == 5
    for fmt in ("html", "json", "txt", "xml", "sarif"):
        assert f"report.{fmt}?download=1" in modal
    # выпадающего меню больше нет
    assert 'class="download-menu"' not in html


def test_download_trigger_opens_dialog(client) -> None:
    """Кнопка объявляет себя диалогом и умеет открывать его без JS-фолбэка."""
    test_client, site = client
    html = test_client.get(f"/sites/{site.id}").text
    start = html.index('id="download-open"')
    button = html[start - 200 : html.index("</button>", start)]
    assert 'aria-haspopup="dialog"' in button
    assert 'aria-controls="download-modal"' in button
    assert 'aria-label="Сохранить отчёт"' in button
    assert f'data-fallback="/api/sites/{site.id}/report.html?download=1"' in button
    # Без JS форматы всё равно доступны: <noscript> с теми же ссылками.
    noscript = html[html.index("<noscript>") : html.index("</noscript>")]
    assert noscript.count("?download=1") == 5


def test_download_modal_closes_on_escape_markup(client) -> None:
    """Закрытие — нативная кнопка: <dialog> закрывается по Esc и с кнопки."""
    test_client, site = client
    modal = _download_modal(test_client.get(f"/sites/{site.id}").text)
    assert "data-download-close" in modal
    assert 'aria-label="Закрыть"' in modal


def test_download_modal_shows_filename_and_date(client) -> None:
    """В окне видно, что именно скачается, и от какой проверки отчёт."""
    test_client, site = client
    modal = _download_modal(test_client.get(f"/sites/{site.id}").text)
    assert "webscope-example.com-" in modal
    assert "расширение зависит от формата" in modal
    assert "проверка от " in modal


def test_download_block_hidden_without_report(client) -> None:
    """Нет отчёта — нечего сохранять: ни кнопки, ни модалки."""

    test_client, _site = client
    response = test_client.post("/sites", data={"url": "https://fresh.example.com"}, follow_redirects=False)
    new_id = int(response.headers["location"].rsplit("/", 1)[-1])
    page = test_client.get(f"/sites/{new_id}").text
    assert 'id="download-open"' not in page
    assert 'id="download-modal"' not in page
    assert "report." not in page


def test_download_filename_is_ascii_and_safe(tmp_path: Path) -> None:
    """Unicode-домены, порты и IPv6 не должны ломать имя файла."""
    from webscope.webapp.app import download_filename
    from webscope.webapp.storage import Storage

    storage = Storage(tmp_path / "names.db")
    site = storage.add_site("https://пример.рф:8443/")
    run = storage.start_run(site.id)
    for ext in ("html", "json", "txt", "xml", "sarif"):
        name = download_filename(site, run, ext)
        assert name.isascii()
        assert name == f"webscope-site-{run.started_at[:10]}.{ext}"
        assert ":" not in name and "/" not in name
    storage.close()


def test_download_filename_keeps_regular_host(tmp_path: Path) -> None:
    from webscope.webapp.app import download_filename
    from webscope.webapp.storage import Storage

    storage = Storage(tmp_path / "plain.db")
    site = storage.add_site("https://example.com/")
    run = storage.start_run(site.id)
    assert download_filename(site, run, "json") == f"webscope-example.com-{run.started_at[:10]}.json"
    storage.close()
