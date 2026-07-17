"""Unit tests for musicvault.db.repositories.artwork_repo."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import Engine

from musicvault.db.repositories.artwork_repo import ArtworkRepository
from musicvault.db.uuid_utils import generate_uuid7
from musicvault.models.entities.artwork import Artwork

_NOW = datetime(2026, 7, 17, tzinfo=UTC)


@pytest.fixture
def artwork_repo(engine: Engine) -> ArtworkRepository:
    return ArtworkRepository(engine)


@pytest.fixture
def album_id(engine: Engine) -> UUID:
    from sqlalchemy import insert

    from musicvault.db.tables import albums
    from musicvault.db.uuid_utils import uuid_to_blob

    alb_id = generate_uuid7()
    with engine.begin() as conn:
        conn.execute(
            insert(albums).values(
                id=uuid_to_blob(alb_id),
                title="OK Computer",
                sort_title="OK Computer",
                created_at="2026-07-15T00:00:00",
                updated_at="2026-07-15T00:00:00",
            )
        )
    return alb_id


def _make_artwork(content_hash: str = "ab" * 32) -> Artwork:
    return Artwork(
        id=generate_uuid7(),
        content_hash_sha256=content_hash,
        source="cover_art_archive",
        mime_type="image/jpeg",
        width=1200,
        height=1200,
        file_size=123_456,
        file_path=f"C:/cache/artwork/{content_hash[:2]}/{content_hash}.jpg",
        created_at=_NOW,
        source_id="release-mbid",
    )


def test_upsert_image_and_get_round_trip(artwork_repo: ArtworkRepository) -> None:
    art = _make_artwork()

    returned_id = artwork_repo.upsert_image(art)

    assert returned_id == art.id
    loaded = artwork_repo.get(art.id)
    assert loaded == art


def test_upsert_image_deduplicates_by_content_hash(artwork_repo: ArtworkRepository) -> None:
    first = _make_artwork()
    duplicate = _make_artwork()  # new UUID, same hash

    first_id = artwork_repo.upsert_image(first)
    second_id = artwork_repo.upsert_image(duplicate)

    assert second_id == first_id
    assert artwork_repo.get(duplicate.id) is None


def test_get_by_content_hash(artwork_repo: ArtworkRepository) -> None:
    art = _make_artwork(content_hash="cd" * 32)
    artwork_repo.upsert_image(art)

    assert artwork_repo.get_by_content_hash("cd" * 32) == art
    assert artwork_repo.get_by_content_hash("ef" * 32) is None


def test_link_track_and_primary_lookup(artwork_repo: ArtworkRepository, track_id: UUID) -> None:
    art = _make_artwork()
    artwork_repo.upsert_image(art)

    artwork_repo.link_track(track_id, art.id)

    assert artwork_repo.has_artwork_for_track(track_id) is True
    assert artwork_repo.get_primary_for_track(track_id) == art


def test_link_track_is_idempotent(artwork_repo: ArtworkRepository, track_id: UUID) -> None:
    art = _make_artwork()
    artwork_repo.upsert_image(art)

    artwork_repo.link_track(track_id, art.id)
    artwork_repo.link_track(track_id, art.id)  # must not raise

    assert artwork_repo.get_primary_for_track(track_id) == art


def test_link_album_and_primary_lookup(artwork_repo: ArtworkRepository, album_id: UUID) -> None:
    art = _make_artwork()
    artwork_repo.upsert_image(art)

    artwork_repo.link_album(album_id, art.id)

    assert artwork_repo.get_primary_for_album(album_id) == art


def test_unlinked_track_has_no_artwork(artwork_repo: ArtworkRepository, track_id: UUID) -> None:
    assert artwork_repo.has_artwork_for_track(track_id) is False
    assert artwork_repo.get_primary_for_track(track_id) is None
