"""Unit tests for the Discogs metadata and artwork providers."""

from __future__ import annotations

import responses

from vaultseek.models.interfaces.artwork import ArtworkQuery
from vaultseek.models.interfaces.metadata import MetadataQuery
from vaultseek.plugins.builtin.discogs import DiscogsArtworkProvider, DiscogsProvider


@responses.activate
def test_lookup_by_id_parses_release() -> None:
    responses.add(
        responses.GET,
        "https://api.discogs.com/releases/249504",
        json={
            "id": 249504,
            "title": "Nevermind",
            "year": 1991,
            "artists": [{"id": 125246, "name": "Nirvana"}],
            "genres": ["Rock"],
            "styles": ["Grunge"],
            "labels": [{"name": "DGC", "catno": "DGCD-24425"}],
            "country": "US",
            "formats": [{"name": "CD"}],
            "tracklist": [
                {"position": "1", "title": "Smells Like Teen Spirit", "type_": "track"},
                {"position": "2", "title": "In Bloom", "type_": "track"},
            ],
        },
    )
    provider = DiscogsProvider(user_token="token")

    result = provider.lookup_by_id("249504", "release")

    assert result is not None
    by_field = {f.field: f.value for f in result.fields}
    assert by_field["discogs_id"] == "249504"
    assert by_field["artist"] == "Nirvana"
    assert by_field["album"] == "Nevermind"
    assert by_field["year"] == 1991
    assert by_field["genre"] == "Rock; Grunge"
    assert by_field["label"] == "DGC"
    assert by_field["catalog_number"] == "DGCD-24425"
    assert by_field["country"] == "US"
    assert by_field["format"] == "CD"
    assert result.lookup_method == "id"


@responses.activate
def test_lookup_by_tags_searches_then_fetches_release() -> None:
    responses.add(
        responses.GET,
        "https://api.discogs.com/database/search",
        json={
            "results": [
                {
                    "id": 249504,
                    "title": "Nirvana - Nevermind",
                    "year": "1991",
                    "genre": ["Rock"],
                    "style": ["Grunge"],
                }
            ]
        },
    )
    responses.add(
        responses.GET,
        "https://api.discogs.com/releases/249504",
        json={
            "id": 249504,
            "title": "Nevermind",
            "year": 1991,
            "artists": [{"id": 125246, "name": "Nirvana"}],
            "genres": ["Rock"],
            "styles": ["Grunge"],
            "labels": [{"name": "DGC", "catno": "DGCD-24425"}],
            "tracklist": [
                {"position": "1", "title": "Smells Like Teen Spirit", "type_": "track"},
            ],
        },
    )
    provider = DiscogsProvider(user_token="token")

    result = provider.lookup_by_tags(
        MetadataQuery(artist="Nirvana", album="Nevermind", title="Smells Like Teen Spirit")
    )

    assert result is not None
    by_field = {f.field: f.value for f in result.fields}
    assert by_field["title"] == "Smells Like Teen Spirit"
    assert by_field["track_number"] == 1
    assert by_field["discogs_id"] == "249504"


def test_lookup_without_token_is_noop() -> None:
    provider = DiscogsProvider(user_token="")
    assert provider.lookup_by_tags(MetadataQuery(artist="A", album="B")) is None
    assert provider.lookup_by_id("1", "release") is None


def test_lookup_by_tags_requires_artist_and_album_or_title() -> None:
    provider = DiscogsProvider(user_token="token")
    assert provider.lookup_by_tags(MetadataQuery(artist="Only")) is None
    assert provider.lookup_by_fingerprint(b"fp", 1.0) is None


@responses.activate
def test_artwork_fetch_by_discogs_id() -> None:
    # Minimal valid 1x1 PNG
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
        b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    responses.add(
        responses.GET,
        "https://api.discogs.com/releases/249504",
        json={
            "id": 249504,
            "images": [
                {
                    "type": "primary",
                    "uri": "https://img.discogs.com/cover.jpg",
                    "width": 600,
                    "height": 600,
                }
            ],
        },
    )
    responses.add(
        responses.GET,
        "https://img.discogs.com/cover.jpg",
        body=png,
        content_type="image/png",
    )
    provider = DiscogsArtworkProvider(user_token="token")

    result = provider.fetch(ArtworkQuery(discogs_id="249504"))

    assert result is not None
    assert result.source == "discogs"
    assert result.source_id == "249504"
    assert result.width >= 1
    assert result.height >= 1


def test_artwork_without_token_is_noop() -> None:
    assert DiscogsArtworkProvider(user_token="").fetch(ArtworkQuery(discogs_id="1")) is None


@responses.activate
def test_get_release_tracklist() -> None:
    responses.add(
        responses.GET,
        "https://api.discogs.com/releases/100",
        json={
            "id": 100,
            "tracklist": [
                {"position": "1", "title": "Intro", "type_": "track", "duration": "1:00"},
                {"position": "", "title": "Side A", "type_": "heading"},
                {"position": "2", "title": "Song", "type_": "track", "duration": "3:20"},
            ],
        },
    )
    provider = DiscogsProvider(user_token="token")
    rows = provider.get_release_tracklist(100)
    assert [row["title"] for row in rows] == ["Intro", "Song"]

    responses.add(
        responses.GET,
        "https://api.discogs.com/artists/112464/releases",
        json={
            "pagination": {"page": 1, "pages": 1},
            "releases": [
                {
                    "id": 2,
                    "title": "Later Album",
                    "year": 2005,
                    "type": "release",
                    "role": "Main",
                    "format": "Album",
                    "label": "Armada",
                    "artist": "Armin van Buuren",
                },
                {
                    "id": 1,
                    "title": "Early Single",
                    "year": 1999,
                    "type": "release",
                    "role": "Main",
                    "format": "Single",
                    "label": "Cyber",
                    "artist": "Armin van Buuren",
                },
            ],
        },
    )
    provider = DiscogsProvider(user_token="token")
    rows = provider.list_artist_releases(112464)
    assert [row["id"] for row in rows] == [1, 2]
    assert rows[0]["title"] == "Early Single"
