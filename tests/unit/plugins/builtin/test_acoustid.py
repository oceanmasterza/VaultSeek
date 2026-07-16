"""Unit tests for the AcoustID HTTP metadata provider."""

from __future__ import annotations

import responses

from musicvault.models.interfaces.metadata import MetadataQuery
from musicvault.plugins.builtin.acoustid import AcoustIdProvider


@responses.activate
def test_lookup_by_fingerprint_parses_best_result() -> None:
    responses.add(
        responses.GET,
        "https://api.acoustid.org/v2/lookup",
        json={
            "status": "ok",
            "results": [
                {
                    "id": "aid-low",
                    "score": 0.50,
                    "recordings": [{"id": "mbid-low", "title": "Low"}],
                },
                {
                    "id": "aid-high",
                    "score": 0.95,
                    "recordings": [
                        {
                            "id": "mbid-high",
                            "title": "High Title",
                            "artists": [{"name": "Artist"}],
                        }
                    ],
                },
            ],
        },
    )
    provider = AcoustIdProvider(api_key="test-key")

    result = provider.lookup_by_fingerprint(b"ABCDEF", 180.0)

    assert result is not None
    by_field = {f.field: f.value for f in result.fields}
    assert by_field["acoustid_id"] == "aid-high"
    assert by_field["mb_recording_id"] == "mbid-high"
    assert by_field["title"] == "High Title"
    assert by_field["artist"] == "Artist"
    assert result.lookup_method == "fingerprint"


def test_lookup_by_fingerprint_without_api_key_returns_none() -> None:
    assert AcoustIdProvider(api_key="").lookup_by_fingerprint(b"fp", 10.0) is None


@responses.activate
def test_lookup_by_fingerprint_returns_none_on_http_error() -> None:
    responses.add(responses.GET, "https://api.acoustid.org/v2/lookup", status=500)
    provider = AcoustIdProvider(api_key="test-key")

    assert provider.lookup_by_fingerprint(b"fp", 10.0) is None


def test_stub_methods_return_empty() -> None:
    provider = AcoustIdProvider(api_key="k")
    assert provider.lookup_by_tags(MetadataQuery()) is None
    assert provider.lookup_by_id("x", "recording") is None
    assert provider.search("q", "recording") == []


@responses.activate
def test_parse_returns_none_when_status_not_ok() -> None:
    responses.add(
        responses.GET,
        "https://api.acoustid.org/v2/lookup",
        json={"status": "error", "results": []},
    )
    assert AcoustIdProvider(api_key="k").lookup_by_fingerprint(b"fp", 1.0) is None


@responses.activate
def test_parse_returns_none_when_results_empty() -> None:
    responses.add(
        responses.GET,
        "https://api.acoustid.org/v2/lookup",
        json={"status": "ok", "results": []},
    )
    assert AcoustIdProvider(api_key="k").lookup_by_fingerprint(b"fp", 1.0) is None
