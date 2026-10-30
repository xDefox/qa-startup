"""Юнит-тесты проверки консоли: без браузера.

`console.run` не обращается к странице — только к тому, что собрал сканер,
поэтому владельца находки (сайт или чужой виджет) можно проверять без Chromium.
"""

from __future__ import annotations


def test_console_warning_from_third_party_is_external() -> None:
    """Предупреждение из чужого SDK — не дефект сайта (как и ошибки)."""
    from webscope.checks import console
    from webscope.context import ScanContext

    ctx = ScanContext(
        url="https://site.com/",
        final_url="https://site.com/",
        title="",
        console_messages=[
            {
                "type": "warning",
                "text": "Deprecation from vendor SDK",
                "location": "https://cdn.vendor.net/sdk.js",
                "location_url": "https://cdn.vendor.net/sdk.js",
            }
        ],
    )
    findings = console.run(None, ctx)
    assert [finding.rule for finding in findings] == ["console/warning"]
    assert findings[0].details["owner"] == "third-party"


def test_console_warning_from_site_is_own() -> None:
    from webscope.checks import console
    from webscope.context import ScanContext

    ctx = ScanContext(
        url="https://site.com/",
        final_url="https://site.com/",
        title="",
        console_messages=[
            {
                "type": "warning",
                "text": "own warning",
                "location": "https://site.com/app.js",
                "location_url": "https://site.com/app.js",
            }
        ],
    )
    findings = console.run(None, ctx)
    assert findings[0].details["owner"] == "site"
