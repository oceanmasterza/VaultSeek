"""Tests for AcoustID endpoint pool."""

from __future__ import annotations

from unittest.mock import MagicMock

from vaultseek.core.config import AcoustIdEndpointConfig
from vaultseek.plugins.builtin.acoustid.pool import AcoustIdProviderPool, build_acoustid_endpoints


def test_build_acoustid_endpoints_from_legacy_key() -> None:
    endpoints = build_acoustid_endpoints(api_key="legacy-key", endpoints=())
    assert len(endpoints) == 1
    assert endpoints[0]._api_key == "legacy-key"


def test_build_acoustid_endpoints_skips_empty() -> None:
    endpoints = build_acoustid_endpoints(
        api_key="",
        endpoints=(
            AcoustIdEndpointConfig(api_key="a", proxy_url="http://p1"),
            AcoustIdEndpointConfig(api_key="", proxy_url=""),
            AcoustIdEndpointConfig(api_key="b", proxy_url="http://p2"),
        ),
    )
    assert len(endpoints) == 2
    assert endpoints[0]._api_key == "a"
    assert endpoints[1]._api_key == "b"


def test_pool_round_robin_endpoints() -> None:
    first = MagicMock()
    first.label = "A"
    second = MagicMock()
    second.label = "B"
    pool = AcoustIdProviderPool([first, second])
    assert pool._next_endpoint() is first
    assert pool._next_endpoint() is second
    assert pool._next_endpoint() is first


def test_acoustid_provider_sets_proxy() -> None:
    from vaultseek.plugins.builtin.acoustid.provider import AcoustIdProvider

    provider = AcoustIdProvider(api_key="test", proxy_url="http://127.0.0.1:8888")
    assert provider._session.proxies.get("http") == "http://127.0.0.1:8888"
