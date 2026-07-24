"""Tests for the Shazamio metadata provider and route pool."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from vaultseek.core.config import AcoustIdEndpointConfig
from vaultseek.plugins.builtin.shazamio.pool import ShazamioProviderPool, build_shazam_routes
from vaultseek.plugins.builtin.shazamio.provider import ShazamioProvider, _parse_shazam_response


def test_build_shazam_routes_always_includes_direct() -> None:
    routes = build_shazam_routes(endpoints=())
    assert len(routes) == 1
    assert routes[0].proxy_url is None
    assert routes[0].label == "Direct"


def test_build_shazam_routes_adds_unique_proxies_without_keys() -> None:
    routes = build_shazam_routes(
        endpoints=(
            AcoustIdEndpointConfig(api_key="", proxy_url="http://p1:8080", label="One"),
            AcoustIdEndpointConfig(api_key="", proxy_url="http://p1:8080", label="Dup"),
            AcoustIdEndpointConfig(api_key="key", proxy_url="http://p2:8080", label="Two"),
            AcoustIdEndpointConfig(api_key="", proxy_url="", label="Empty"),
        )
    )
    assert len(routes) == 3
    assert routes[0].proxy_url is None
    assert routes[1].proxy_url == "http://p1:8080"
    assert routes[1].label == "One"
    assert routes[2].proxy_url == "http://p2:8080"


def test_pool_round_robin_routes() -> None:
    first = MagicMock()
    first.label = "Direct"
    second = MagicMock()
    second.label = "Proxy"
    pool = ShazamioProviderPool([first, second])
    assert pool._next_route() is first
    assert pool._next_route() is second
    assert pool._next_route() is first


def test_parse_shazam_response_extracts_core_fields() -> None:
    payload = {
        "track": {
            "key": "123",
            "title": "Karma Police",
            "subtitle": "Radiohead",
            "sections": [
                {
                    "type": "SONG",
                    "metadata": [
                        {"title": "Album", "text": "OK Computer"},
                        {"title": "ISRC", "text": "GBAYE9701370"},
                    ],
                }
            ],
        }
    }
    result = _parse_shazam_response(payload, priority=6)
    assert result is not None
    assert result.provider_id == "shazamio"
    assert result.lookup_method == "audio"
    by_field = {field.field: field.value for field in result.fields}
    assert by_field["title"] == "Karma Police"
    assert by_field["artist"] == "Radiohead"
    assert by_field["album"] == "OK Computer"
    assert by_field["isrc"] == "GBAYE9701370"
    assert by_field["shazam_track_id"] == "123"


def test_parse_shazam_response_empty_track_returns_none() -> None:
    assert _parse_shazam_response({"matches": []}, priority=6) is None
    assert _parse_shazam_response({"track": {}}, priority=6) is None


def test_recognize_file_uses_backend_and_proxy() -> None:
    provider = ShazamioProvider(proxy_url="http://proxy:1", label="P")
    fake_payload = {
        "track": {"key": "1", "title": "T", "subtitle": "A"},
    }
    with patch(
        "vaultseek.plugins.builtin.shazamio.provider.recognize_with_shazamio",
        return_value=fake_payload,
    ) as mock_recognize:
        result = provider.recognize_file("C:/music/song.flac")
    mock_recognize.assert_called_once_with("C:/music/song.flac", proxy_url="http://proxy:1")
    assert result is not None
    assert result.fields[0].field in {"shazam_track_id", "title", "artist"}
