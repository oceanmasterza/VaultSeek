"""Unit tests for musicvault.db.repositories.artist_repo.ArtistRepository."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Engine

from musicvault.db.repositories.artist_repo import ArtistRepository
from musicvault.db.uuid_utils import generate_uuid7
from musicvault.models.entities.artist import Artist

_NOW = datetime(2026, 7, 15, tzinfo=UTC)


def _make_artist(**overrides: object) -> Artist:
    defaults: dict[str, object] = {
        "id": generate_uuid7(),
        "name": "Allen Watts",
        "sort_name": "Watts, Allen",
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    defaults.update(overrides)
    return Artist(**defaults)  # type: ignore[arg-type]


def test_create_and_get_round_trips_every_field(engine: Engine) -> None:
    repo = ArtistRepository(engine)
    artist = _make_artist(mbid="mbid-1", discogs_id="discogs-1", type="Person", country="NL")

    repo.create(artist)
    loaded = repo.get(artist.id)

    assert loaded == artist


def test_get_returns_none_for_missing_artist(engine: Engine) -> None:
    repo = ArtistRepository(engine)

    assert repo.get(generate_uuid7()) is None


def test_batch_create_persists_multiple_artists(engine: Engine) -> None:
    repo = ArtistRepository(engine)
    batch = [_make_artist(name=f"Artist {i}") for i in range(5)]

    repo.batch_create(batch)

    loaded_ids = {loaded.id for artist in batch if (loaded := repo.get(artist.id)) is not None}
    assert loaded_ids == {artist.id for artist in batch}


def test_get_by_mbid_finds_matching_artist(engine: Engine) -> None:
    repo = ArtistRepository(engine)
    artist = _make_artist(mbid="mbid-unique")
    repo.create(artist)

    assert repo.get_by_mbid("mbid-unique") == artist
    assert repo.get_by_mbid("no-such-mbid") is None


def test_list_by_name_returns_every_matching_artist(engine: Engine) -> None:
    repo = ArtistRepository(engine)
    first = _make_artist(name="The Band")
    second = _make_artist(name="The Band")
    other = _make_artist(name="Someone Else")
    repo.create(first)
    repo.create(second)
    repo.create(other)

    results = repo.list_by_name("The Band")

    assert {artist.id for artist in results} == {first.id, second.id}
