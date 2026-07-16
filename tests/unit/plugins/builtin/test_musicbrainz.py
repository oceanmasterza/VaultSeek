"""Unit tests for the MusicBrainz metadata provider."""

from __future__ import annotations

import responses

from musicvault.models.interfaces.metadata import MetadataQuery
from musicvault.plugins.builtin.musicbrainz import MusicBrainzProvider


@responses.activate
def test_lookup_by_id_parses_recording() -> None:
    mbid = "12345678-1234-1234-1234-123456789abc"
    responses.add(
        responses.GET,
        f"https://musicbrainz.org/ws/2/recording/{mbid}",
        json={
            "id": mbid,
            "title": "Karma Police",
            "artist-credit": [{"name": "Radiohead"}],
            "releases": [{"title": "OK Computer", "date": "1997-05-21"}],
        },
    )
    provider = MusicBrainzProvider()

    result = provider.lookup_by_id(mbid, "recording")

    assert result is not None
    by_field = {f.field: f.value for f in result.fields}
    assert by_field["mb_recording_id"] == mbid
    assert by_field["title"] == "Karma Police"
    assert by_field["artist"] == "Radiohead"
    assert by_field["album"] == "OK Computer"
    assert by_field["year"] == 1997
    assert result.lookup_method == "id"


@responses.activate
def test_lookup_by_tags_requires_artist_and_title() -> None:
    responses.add(
        responses.GET,
        "https://musicbrainz.org/ws/2/recording/",
        json={"recordings": [{"id": "mbid", "title": "Song", "artist-credit": [{"name": "A"}]}]},
    )
    provider = MusicBrainzProvider()

    assert provider.lookup_by_tags(MetadataQuery(title="Only")) is None
    result = provider.lookup_by_tags(MetadataQuery(artist="A", title="Song"))
    assert result is not None
    assert result.lookup_method == "tags"


@responses.activate
def test_lookup_by_id_returns_none_on_http_error() -> None:
    responses.add(
        responses.GET,
        "https://musicbrainz.org/ws/2/recording/bad",
        status=404,
    )
    assert MusicBrainzProvider().lookup_by_id("bad", "recording") is None


def test_stub_and_guard_paths() -> None:
    provider = MusicBrainzProvider()
    assert provider.lookup_by_fingerprint(b"fp", 1.0) is None
    assert provider.lookup_by_id("", "recording") is None
    assert provider.lookup_by_id("x", "artist") is None
    assert provider.search("q", "artist") == []
    assert provider.search("  ", "recording") == []


@responses.activate
def test_lookup_by_tags_returns_none_when_no_recordings() -> None:
    responses.add(
        responses.GET,
        "https://musicbrainz.org/ws/2/recording/",
        json={"recordings": []},
    )
    assert MusicBrainzProvider().lookup_by_tags(MetadataQuery(artist="A", title="B")) is None


@responses.activate
def test_search_returns_recording_results() -> None:
    responses.add(
        responses.GET,
        "https://musicbrainz.org/ws/2/recording/",
        json={
            "recordings": [
                {"id": "mb1", "title": "One", "artist-credit": [{"name": "A"}]},
                {"id": "mb2", "title": "Two"},
            ]
        },
    )
    results = MusicBrainzProvider().search("query", "recording", limit=2)
    assert len(results) == 2
    assert results[0].lookup_method == "search"
