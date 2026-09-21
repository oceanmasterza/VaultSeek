"""Unit tests for album-context duplicate helpers."""

from __future__ import annotations

from datetime import UTC, datetime

from vaultseek.db.uuid_utils import generate_uuid7
from vaultseek.models.entities.album import Album
from vaultseek.models.services.album_context import albums_equivalent

_NOW = datetime(2026, 7, 19, tzinfo=UTC)


def _album(**overrides: object) -> Album:
    defaults: dict[str, object] = {
        "id": generate_uuid7(),
        "title": "OK Computer",
        "sort_title": "OK Computer",
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    defaults.update(overrides)
    return Album(**defaults)  # type: ignore[arg-type]


def test_albums_equivalent_by_release_mbid() -> None:
    assert albums_equivalent(
        _album(mbid="r1", title="A"),
        _album(mbid="r1", title="B"),
    )


def test_albums_equivalent_by_release_group() -> None:
    assert albums_equivalent(
        _album(release_group_mbid="rg1", title="A"),
        _album(release_group_mbid="rg1", title="B"),
    )


def test_albums_equivalent_by_title_and_artist() -> None:
    artist = generate_uuid7()
    assert albums_equivalent(
        _album(title="OK Computer", album_artist_id=artist),
        _album(title="ok computer", album_artist_id=artist),
    )


def test_albums_not_equivalent_same_title_different_artists() -> None:
    assert not albums_equivalent(
        _album(title="Greatest Hits", album_artist_id=generate_uuid7()),
        _album(title="Greatest Hits", album_artist_id=generate_uuid7()),
    )


def test_albums_not_equivalent_title_alone_without_artist() -> None:
    assert not albums_equivalent(_album(title="OK Computer"), _album(title="OK Computer"))


def test_release_cover_key_strips_edition_notes_only() -> None:
    from vaultseek.models.services.album_context import release_cover_key

    salvation = release_cover_key("Alphaville", "Salvation (Deluxe Version)")
    remaster = release_cover_key("Alphaville", "Salvation (Deluxe Remaster 2023) [3CD]")
    no_limit = release_cover_key("2 Unlimited", "No Limit - EP")
    assert salvation == remaster
    assert salvation != no_limit
    assert release_cover_key("Alice In Chains", "Alice In Chains") == release_cover_key(
        "alice in chains", "Alice In Chains"
    )


def test_release_cover_key_keeps_live_remix_and_volume_titles() -> None:
    from vaultseek.models.services.album_context import release_cover_key

    assert release_cover_key("Pink Floyd", "The Wall") != release_cover_key(
        "Pink Floyd", "The Wall (Live)"
    )
    assert release_cover_key("Artist", "Hits") != release_cover_key("Artist", "Hits (Acoustic)")
    assert release_cover_key("Artist", "Song") != release_cover_key("Artist", "Song (Remix)")
    assert release_cover_key("Artist", "Album") != release_cover_key(
        "Artist", "Album (feat. Guest)"
    )
    assert release_cover_key("Artist", "Vol 1") != release_cover_key("Artist", "Vol 1 (Blue Album)")


def test_release_slot_key_treats_nonpositive_as_unnumbered() -> None:
    from vaultseek.db.uuid_utils import generate_uuid7
    from vaultseek.models.services.album_context import release_slot_key

    a = generate_uuid7()
    b = generate_uuid7()
    assert release_slot_key(1, 0, a, "A") != release_slot_key(1, 0, b, "B")
    assert release_slot_key(1, None, a) != release_slot_key(1, None, b)
    assert release_slot_key(1, 1, a, "Same") == release_slot_key(1, 1, b, "same")
    assert release_slot_key(1, 1, a, "One") != release_slot_key(1, 1, b, "Two")
