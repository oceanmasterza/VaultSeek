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
