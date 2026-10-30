"""Страница отчёта: все находки в одной таблице и все три категории.

Категории: дефекты сайта по серьёзности (критично/существенно/желательно/мелочи)
и отдельная группа «замечания сканирования» — ошибки чужих виджетов.
"""

from __future__ import annotations

import json
import shutil
import subprocess
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
    # Рядом с ним такая же иконка «сохранить отчёт» (стрелка вниз), но это
    # отдельный класс: иначе клик по ней срабатывал бы как переключение вида.
    assert html.count('class="view-btn"') == 2
    assert html.count('class="icon-btn download-btn"') == 1
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


def test_download_is_available_from_site_page(client) -> None:
    test_client, site = client
    page = test_client.get(f"/sites/{site.id}")
    assert page.status_code == 200
    assert 'id="download-pop"' in page.text
    assert "Сохранить отчёт" in page.text
    for fmt in ("html", "json", "txt", "xml", "sarif"):
        assert f"/api/sites/{site.id}/report.{fmt}?download=1" in page.text


def test_three_buttons_do_not_replace_the_report(client) -> None:
    """Список и таблица меняют вид находок, «скачать» — только показывает форматы.

    Панель форматов не модалка: она всплывает поверх таблицы, но фон не гасит
    и разметку находок не трогает — таблица и список остаются в документе.
    """
    test_client, site = client
    html = test_client.get(f"/sites/{site.id}").text
    assert html.count('class="view-btn"') == 2, "переключатель вида"
    assert html.count('class="icon-btn download-btn"') == 1, "кнопка сохранения"
    # обе панели находок на месте, даже когда открыт выбор формата
    assert html.count('class="findings-view"') == 2
    assert 'class="findings-table"' in html
    # и это не диалог: диалог гасит страницу под собой
    assert "<dialog" not in html
    assert "download-modal" not in html


def test_download_trigger_sits_next_to_view_toggle(client) -> None:
    """Сохранение — в шапке находок, рядом с переключателем «списком/таблицей»."""
    test_client, site = client
    html = test_client.get(f"/sites/{site.id}").text
    head = html.index('class="findings-head"')
    toggle = html.index('class="view-toggle"', head)
    trigger = html.index('id="download-open"', head)
    table = html.index('class="findings-table"', head)
    assert head < toggle < trigger < table, "кнопка сохранения — в шапке, сразу за переключателем вида"
    assert trigger > html.index("Проверить ещё раз"), "и ниже шапки страницы"


def test_download_panel_is_hidden_until_opened(client) -> None:
    """Панель лежит в разметке скрытой и не влияет на вёрстку отчёта."""
    test_client, site = client
    html = test_client.get(f"/sites/{site.id}").text
    panel_start = html.index('class="download-pop"')
    panel = html[panel_start : html.index('<div class="findings-view" data-mode="table"', panel_start)]
    assert "hidden" in panel[:80], "панель должна быть скрыта до нажатия"
    assert panel.count('class="download-option"') == 5
    for fmt in ("html", "json", "txt", "xml", "sarif"):
        assert f"report.{fmt}?download=1" in panel
    assert 'id="download-name"' in panel, "можно задать своё имя файла"
    assert 'value="webscope-example.com-' in panel, "по умолчанию — домен и дата"
    assert 'id="download-name-ext"' in panel


def test_download_trigger_declares_a_popup(client) -> None:
    test_client, site = client
    html = test_client.get(f"/sites/{site.id}").text
    start = html.index('id="download-open"')
    button = html[start - 200 : html.index("</button>", start)]
    assert 'aria-haspopup="true"' in button
    assert 'aria-expanded="false"' in button
    assert 'aria-controls="download-pop"' in button
    assert 'aria-label="Сохранить отчёт"' in button
    # Без JS форматы всё равно доступны: <noscript> с теми же ссылками.
    noscript = html[html.index("<noscript>") : html.index("</noscript>")]
    assert noscript.count("?download=1") == 5


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


HARNESS = Path(__file__).parent / "js" / "report_page_harness.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="нужен node для исполнения скрипта страницы")
def test_download_button_does_not_change_findings_view(client) -> None:
    """Клик по «скачать» не должен прятать таблицу или список находок.

    Регресс: у кнопки сохранения был класс `view-btn`, обработчик переключателя
    вида вешался на все `.view-btn`, получал `dataset.view === undefined` и прятал
    обе панели находок — выглядело как «таблица пропала».

    Проверка настоящая: берём отрендеренную страницу, исполняем её скрипт
    в мини-DOM (tests/js/report_page_harness.js) и кликаем по кнопкам.
    """
    test_client, site = client
    html = test_client.get(f"/sites/{site.id}").text

    completed = subprocess.run(
        ["node", str(HARNESS)],
        input=json.dumps({"html": html}),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    payload = json.loads(completed.stdout or "{}")
    assert payload.get("ok"), payload
    assert payload["initialVisible"] == ["list"]
    assert payload["afterDownloadClick"] == ["list"], "после «скачать» вид находок не меняется"
    assert payload["afterTableToggle"] == ["table"]
    assert payload["afterDownloadClickOnTable"] == ["table"], "и на таблице тоже"
    assert payload["popOpened"] is True


@pytest.mark.skipif(shutil.which("node") is None, reason="нужен node для исполнения скрипта страницы")
def test_filename_field_updates_download_links(client) -> None:
    """Поле имени файла переписывает ссылки: имя, расширение, без пути и CRLF."""
    test_client, site = client
    html = test_client.get(f"/sites/{site.id}").text

    completed = subprocess.run(
        ["node", str(HARNESS)],
        input=json.dumps({"html": html}),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    payload = json.loads(completed.stdout or "{}")
    checks = payload.get("nameChecks") or {}
    assert checks, payload.get("error") or payload
    assert all(checks.values()), checks
    assert payload["namedDownload"][0] == "мой отчёт за октябрь.html"
    assert payload["namedHrefs"][0].endswith(
        "&filename=%D0%BC%D0%BE%D0%B9%20%D0%BE%D1%82%D1%87%D1%91%D1%82%20%D0%B7%D0%B0%20%D0%BE%D0%BA%D1%82%D1%8F%D0%B1%D1%80%D1%8C"
    )


def test_download_button_is_not_a_view_toggle(client) -> None:
    """Кнопка сохранения не должна попадать в обработчик переключателя вида."""
    test_client, site = client
    html = test_client.get(f"/sites/{site.id}").text
    start = html.index('id="download-open"')
    button = html[html.index("<button", start - 300) : html.index("</button>", start)]
    assert "view-btn" not in button, "класс view-btn навесил бы переключатель вида на сохранение"
    assert "icon-btn" in button
    assert "data-view" not in button
    # и обработчик слушает только переключатель
    assert "'.view-toggle .view-btn'" in html
    assert "if (mode !== 'list' && mode !== 'table') return;" in html


# --- имя файла, выбранное пользователем ---


@pytest.mark.parametrize("fmt", ["html", "json", "txt", "xml", "sarif"])
def test_download_uses_custom_filename(client, fmt: str) -> None:
    """Имя из поля ввода попадает в Content-Disposition с нужным расширением."""
    test_client, site = client
    response = test_client.get(f"/api/sites/{site.id}/report.{fmt}?download=1&filename=my-report")
    assert response.headers["content-disposition"] == f'attachment; filename="my-report.{fmt}"'


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("../../etc/passwd", "passwd"),  # путь — это имя, а не путь
        ("../..", None),  # после чистки пусто → имя по умолчанию
        ("report.html", "report"),  # чужое расширение отбрасывается
        ("  my  report  ", "my report"),  # лишние пробелы сжимаются
        ('"; drop table', "drop table"),  # кавычки и точка с запятой вычищены
        ("a\r\nSet-Cookie: x=1", "aSet-Cookie- x-1"),  # CRLF не проходит в заголовок
        ("...", None),
        ("", None),
    ],
)
def test_custom_filename_is_sanitized(client, raw: str, expected: str | None) -> None:
    """Имя уходит в заголовок ответа — всё опасное вычищается."""
    test_client, site = client
    response = test_client.get(f"/api/sites/{site.id}/report.json", params={"download": 1, "filename": raw})
    disposition = response.headers["content-disposition"]
    assert "\r" not in disposition and "\n" not in disposition
    assert '"; ' not in disposition
    if expected is None:
        assert 'filename="webscope-example.com-' in disposition
    else:
        assert disposition == f'attachment; filename="{expected}.json"'


def test_custom_filename_supports_cyrillic(client) -> None:
    """Кириллица идёт в filename* (RFC 6266), ASCII-запасной — имя по умолчанию."""
    test_client, site = client
    response = test_client.get(f"/api/sites/{site.id}/report.html?download=1&filename=мой отчёт")
    disposition = response.headers["content-disposition"]
    assert 'filename="webscope-example.com-' in disposition, "старым клиентам — понятное имя"
    assert "filename*=UTF-8''" in disposition
    assert "%D0%BC%D0%BE%D0%B9%20%D0%BE%D1%82%D1%87%D1%91%D1%82" in disposition


def test_custom_filename_ignored_without_download(client) -> None:
    """Без ?download=1 отчёт открывается в браузере, имя ни на что не влияет."""
    test_client, site = client
    response = test_client.get(f"/api/sites/{site.id}/report.json?filename=my-report")
    assert "content-disposition" not in response.headers


def test_filename_stem_limits_length() -> None:
    from webscope.webapp.app import MAX_FILENAME_STEM, safe_report_stem

    stem = safe_report_stem("x" * 500)
    assert stem is not None
    assert len(stem) == MAX_FILENAME_STEM
