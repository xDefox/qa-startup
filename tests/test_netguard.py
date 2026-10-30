"""SSRF-защита: непубличные адреса закрыты на каждом запросе.

`validate_target` проверял только стартовый адрес, а редирект на
`169.254.169.254` или подгрузка с loopback проходили — и отчёт мог утащить
внутренние данные наружу.
"""

from __future__ import annotations

import httpx
import pytest

from webscope.netguard import GuardedTransport, host_resolves_to_private, url_targets_private_network

# --- SSRF ---


def test_guard_blocks_private_addresses_and_allows_public() -> None:
    assert url_targets_private_network("http://127.0.0.1:8080/") is True
    assert url_targets_private_network("http://localhost/") is True
    assert url_targets_private_network("http://169.254.169.254/latest/meta-data/") is True
    assert url_targets_private_network("http://10.0.0.5/") is True
    assert url_targets_private_network("http://8.8.8.8/") is False
    # не http(s) — не сеть
    assert url_targets_private_network("data:text/html,hi") is False


def test_guarded_transport_blocks_localhost(local_site: str) -> None:
    with (
        httpx.Client(transport=GuardedTransport(allow_private=False), timeout=5) as client,
        pytest.raises(httpx.ConnectError),
    ):
        client.get(f"{local_site}/")


def test_guarded_transport_allows_localhost_when_explicit(local_site: str) -> None:
    with httpx.Client(transport=GuardedTransport(allow_private=True), timeout=5) as client:
        assert client.get(f"{local_site}/").status_code == 200


def test_crawl_respects_private_network_block(local_site: str) -> None:
    from webscope.crawler import crawl

    blocked = crawl(f"{local_site}/", max_pages=3)
    assert blocked.pages == []

    allowed = crawl(f"{local_site}/", max_pages=3, allow_private=True)
    assert allowed.pages


def test_host_resolves_to_private_for_unresolvable_host() -> None:
    assert host_resolves_to_private("this-host-does-not-exist-xyzqwe.invalid") is True
