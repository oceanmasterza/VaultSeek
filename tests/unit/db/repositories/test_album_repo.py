"""Unit tests for musicvault.db.repositories.album_repo.AlbumRepository."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Engine

from musicvault.db.repositories.album_repo import AlbumRepository
from musicvault.db.uuid_utils import generate_uuid7
from musicvault.models.entities.album import Album

_NOW = datetime(2026, 7, 15, tzinfo=UTC)


def _make_album(**overrides: object) -> Album:
    defaults: dict[str, object] = {
        "id": generate_uuid7(),
        "title": "Indicator",
        "sort_title": "Indicator",
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    defaults.update(overrides)
    return Album(**defaults)  # type: ignore[arg-type]


def test_create_and_get_round_trips_every_field(engine: Engine, artist_id: UUID) -> None:
    repo = AlbumRepository(engine)
    album = _make_album(
        album_artist_id=artist_id,
        year=2024,
        mbid="mbid-1",
        release_group_mbid="rg-1",
        discogs_id="discogs-1",
        type="Album",
        genre="Trance",
        disc_count=2,
        track_count=20,
        is_compilation=True,
    )

    repo.create(album)
    loaded = repo.get(album.id)

    assert loaded == album


def test_get_returns_none_for_missing_album(engine: Engine) -> None:
    repo = AlbumRepository(engine)

    assert repo.get(generate_uuid7()) is None


def test_batch_create_persists_multiple_albums(engine: Engine) -> None:
    repo = AlbumRepository(engine)
    batch = [_make_album(title=f"Album {i}") for i in range(5)]

    repo.batch_create(batch)

    loaded_ids = {loaded.id for album in batch if (loaded := repo.get(album.id)) is not None}
    assert loaded_ids == {album.id for album in batch}


def test_get_by_mbid_finds_matching_album(engine: Engine) -> None:
    repo = AlbumRepository(engine)
    album = _make_album(mbid="mbid-unique")
    repo.create(album)

    assert repo.get_by_mbid("mbid-unique") == album
    assert repo.get_by_mbid("no-such-mbid") is None


def test_list_by_artist_returns_only_that_artists_albums(engine: Engine, artist_id: UUID) -> None:
    repo = AlbumRepository(engine)
    matching = _make_album(album_artist_id=artist_id)
    other = _make_album()
    repo.create(matching)
    repo.create(other)

    results = repo.list_by_artist(artist_id)

    assert {album.id for album in results} == {matching.id}
