"""Unit tests for the Cover Art Archive artwork provider."""

from __future__ import annotations

import io

import responses
from PIL import Image

from musicvault.models.interfaces.artwork import ArtworkQuery
from musicvault.plugins.builtin.cover_art_archive import CoverArtArchiveProvider

_RELEASE_MBID = "11111111-1111-1111-1111-111111111111"
_GROUP_MBID = "22222222-2222-2222-2222-222222222222"
_RECORDING_MBID = "33333333-3333-3333-3333-333333333333"


def _png(width: int = 800, height: int = 800) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), "red").save(buffer, "PNG")
    return buffer.getvalue()


@responses.activate
def test_fetch_by_release_id_returns_image_with_dimensions() -> None:
    responses.add(
        responses.GET,
        f"https://coverartarchive.org/release/{_RELEASE_MBID}/front",
        body=_png(1200, 1000),
        content_type="image/png",
    )

    result = CoverArtArchiveProvider().fetch(ArtworkQuery(mb_release_id=_RELEASE_MBID))

    assert result is not None
    assert result.source == "cover_art_archive"
    assert result.mime_type == "image/png"
    assert (result.width, result.height) == (1200, 1000)
    assert result.confidence == 0.95
    assert result.source_id == _RELEASE_MBID


@responses.activate
def test_fetch_by_release_group_id_when_no_release_id() -> None:
    responses.add(
        responses.GET,
        f"https://coverartarchive.org/release-group/{_GROUP_MBID}/front",
        body=_png(),
        content_type="image/jpeg",
    )

    result = CoverArtArchiveProvider().fetch(ArtworkQuery(mb_release_group_id=_GROUP_MBID))

    assert result is not None
    assert result.confidence == 0.85
    assert result.source_id == _GROUP_MBID


@responses.activate
def test_fetch_by_recording_id_resolves_a_release_first() -> None:
    responses.add(
        responses.GET,
        f"https://musicbrainz.org/ws/2/recording/{_RECORDING_MBID}",
        json={"releases": [{"id": _RELEASE_MBID, "title": "OK Computer"}]},
    )
    responses.add(
        responses.GET,
        f"https://coverartarchive.org/release/{_RELEASE_MBID}/front",
        body=_png(),
        content_type="image/jpeg",
    )

    result = CoverArtArchiveProvider().fetch(ArtworkQuery(mb_recording_id=_RECORDING_MBID))

    assert result is not None
    assert result.confidence == 0.80
    assert result.source_id == _RELEASE_MBID


@responses.activate
def test_fetch_returns_none_when_archive_has_no_cover() -> None:
    responses.add(
        responses.GET,
        f"https://coverartarchive.org/release/{_RELEASE_MBID}/front",
        status=404,
    )

    assert CoverArtArchiveProvider().fetch(ArtworkQuery(mb_release_id=_RELEASE_MBID)) is None


@responses.activate
def test_fetch_returns_none_for_undecodable_bytes() -> None:
    responses.add(
        responses.GET,
        f"https://coverartarchive.org/release/{_RELEASE_MBID}/front",
        body=b"this is not an image",
        content_type="image/jpeg",
    )

    assert CoverArtArchiveProvider().fetch(ArtworkQuery(mb_release_id=_RELEASE_MBID)) is None


@responses.activate
def test_fetch_returns_none_when_recording_has_no_releases() -> None:
    responses.add(
        responses.GET,
        f"https://musicbrainz.org/ws/2/recording/{_RECORDING_MBID}",
        json={"releases": []},
    )

    assert CoverArtArchiveProvider().fetch(ArtworkQuery(mb_recording_id=_RECORDING_MBID)) is None


def test_fetch_returns_none_without_any_musicbrainz_handle() -> None:
    assert CoverArtArchiveProvider().fetch(ArtworkQuery(file_path="C:/x.flac")) is None
