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
    assert html.count('class="view-btn"') == 2
    assert "☰" not in html and "⊞" not in html
    assert 'aria-label="Списком"' in html and 'aria-label="Таблицей"' in html

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
