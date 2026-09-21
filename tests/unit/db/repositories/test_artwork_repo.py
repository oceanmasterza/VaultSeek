"""Unit tests for vaultseek.db.repositories.artwork_repo."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import Engine

from vaultseek.db.repositories.artwork_repo import ArtworkRepository
from vaultseek.db.uuid_utils import generate_uuid7
from vaultseek.models.entities.artwork import Artwork

_NOW = datetime(2026, 7, 17, tzinfo=UTC)


@pytest.fixture
def artwork_repo(engine: Engine) -> ArtworkRepository:
    return ArtworkRepository(engine)


@pytest.fixture
def album_id(engine: Engine) -> UUID:
    from sqlalchemy import insert

    from vaultseek.db.tables import albums
    from vaultseek.db.uuid_utils import uuid_to_blob

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


def test_upsert_image_recovers_from_content_hash_race(
    artwork_repo: ArtworkRepository, engine: Engine
) -> None:
    """Simulate a concurrent insert that won the unique content_hash race."""
    from sqlalchemy import insert

    from vaultseek.db.tables import artwork as artwork_table
    from vaultseek.db.uuid_utils import uuid_to_blob

    winner = _make_artwork(content_hash="cd" * 32)
    with engine.begin() as conn:
        conn.execute(
            insert(artwork_table).values(
                id=uuid_to_blob(winner.id),
                content_hash_sha256=winner.content_hash_sha256,
                source=winner.source,
                source_id=winner.source_id,
                mime_type=winner.mime_type,
                width=winner.width,
                height=winner.height,
                file_size=winner.file_size,
                file_path=winner.file_path,
                created_at=winner.created_at.isoformat(),
            )
        )

    loser = _make_artwork(content_hash="cd" * 32)
    returned = artwork_repo.upsert_image(loser)
    assert returned == winner.id


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


def _insert_album(
    engine: Engine,
    *,
    title: str,
    artist_name: str,
    created_at: str = "2026-07-15T00:00:00",
    mbid: str | None = None,
) -> UUID:
    from sqlalchemy import insert

    from vaultseek.db.tables import albums, artists
    from vaultseek.db.uuid_utils import uuid_to_blob

    album_id = generate_uuid7()
    artist_id = generate_uuid7()
    with engine.begin() as conn:
        conn.execute(
            insert(artists).values(
                id=uuid_to_blob(artist_id),
                name=artist_name,
                sort_name=artist_name,
                created_at=created_at,
                updated_at=created_at,
            )
        )
        conn.execute(
            insert(albums).values(
                id=uuid_to_blob(album_id),
                title=title,
                sort_title=title,
                album_artist_id=uuid_to_blob(artist_id),
                mbid=mbid,
                created_at=created_at,
                updated_at=created_at,
            )
        )
    return album_id


def test_link_album_refuses_a_different_release(
    artwork_repo: ArtworkRepository, engine: Engine
) -> None:
    salvation = _insert_album(engine, title="Salvation (Deluxe Version)", artist_name="Alphaville")
    no_limit = _insert_album(engine, title="No Limit - EP", artist_name="2 Unlimited")
    art = _make_artwork()
    artwork_repo.upsert_image(art)

    assert artwork_repo.link_album(salvation, art.id) is True
    assert artwork_repo.link_album(no_limit, art.id) is False
    assert artwork_repo.get_primary_for_album(salvation) == art
    assert artwork_repo.get_primary_for_album(no_limit) is None


def test_same_release_editions_may_share_a_cover(
    artwork_repo: ArtworkRepository, engine: Engine
) -> None:
    original = _insert_album(engine, title="Salvation", artist_name="Alphaville")
    deluxe = _insert_album(
        engine, title="Salvation (Deluxe Remaster 2023) [3CD]", artist_name="Alphaville"
    )
    art = _make_artwork(content_hash="11" * 32)
    artwork_repo.upsert_image(art)

    assert artwork_repo.link_album(original, art.id) is True
    assert artwork_repo.link_album(deluxe, art.id) is True
    assert artwork_repo.get_primary_for_album(deluxe) == art


def test_shared_cover_stays_with_provenanced_release(
    artwork_repo: ArtworkRepository, engine: Engine, library_id: UUID
) -> None:
    """Ambiguous dual primaries hide; MBID/source_id provenance keeps the correct one."""
    from sqlalchemy import insert

    from vaultseek.db.tables import album_artwork, tracks
    from vaultseek.db.uuid_utils import uuid_to_blob

    salvation = _insert_album(
        engine,
        title="Salvation (Deluxe Version)",
        artist_name="Alphaville",
        created_at="2026-09-16T22:30:29",
        mbid="salvation-mbid",
    )
    no_limit = _insert_album(
        engine,
        title="No Limit - EP",
        artist_name="2 Unlimited",
        created_at="2026-09-16T22:36:28",
    )
    art = _make_artwork(content_hash="22" * 32)
    art = Artwork(
        id=art.id,
        content_hash_sha256=art.content_hash_sha256,
        source=art.source,
        mime_type=art.mime_type,
        width=art.width,
        height=art.height,
        file_size=art.file_size,
        file_path=art.file_path,
        created_at=art.created_at,
        source_id="salvation-mbid",
    )
    artwork_repo.upsert_image(art)
    with engine.begin() as conn:
        for album_id in (salvation, no_limit):
            conn.execute(
                insert(album_artwork).values(
                    album_id=uuid_to_blob(album_id),
                    artwork_id=uuid_to_blob(art.id),
                    role="front",
                    is_primary=True,
                )
            )
        for index in range(3):
            conn.execute(
                insert(tracks).values(
                    id=uuid_to_blob(generate_uuid7()),
                    library_id=uuid_to_blob(library_id),
                    album_id=uuid_to_blob(salvation),
                    zone="library",
                    file_path=f"C:/library/salvation/{index}.mp3",
                    file_name=f"{index}.mp3",
                    file_size=1,
                    file_modified="2026-07-15T00:00:00",
                    track_number=index + 1,
                    created_at="2026-07-15T00:00:00",
                    updated_at="2026-07-15T00:00:00",
                )
            )
        conn.execute(
            insert(tracks).values(
                id=uuid_to_blob(generate_uuid7()),
                library_id=uuid_to_blob(library_id),
                album_id=uuid_to_blob(no_limit),
                zone="library",
                file_path="C:/library/nolimit/19.mp3",
                file_name="19.mp3",
                file_size=1,
                file_modified="2026-07-15T00:00:00",
                track_number=19,
                created_at="2026-07-15T00:00:00",
                updated_at="2026-07-15T00:00:00",
            )
        )

    assert artwork_repo.get_primary_for_album(salvation) == art
    assert artwork_repo.get_primary_for_album(no_limit) is None


def test_sole_wrong_owner_does_not_block_provenanced_claim(
    artwork_repo: ArtworkRepository, engine: Engine
) -> None:
    from sqlalchemy import insert

    from vaultseek.db.tables import album_artwork
    from vaultseek.db.uuid_utils import uuid_to_blob

    no_limit = _insert_album(engine, title="No Limit - EP", artist_name="2 Unlimited")
    salvation = _insert_album(
        engine,
        title="Salvation (Deluxe Version)",
        artist_name="Alphaville",
        mbid="salvation-mbid",
    )
    art = _make_artwork(content_hash="55" * 32)
    art = Artwork(
        id=art.id,
        content_hash_sha256=art.content_hash_sha256,
        source="cover_art_archive",
        mime_type=art.mime_type,
        width=art.width,
        height=art.height,
        file_size=art.file_size,
        file_path=art.file_path,
        created_at=art.created_at,
        source_id="salvation-mbid",
    )
    artwork_repo.upsert_image(art)
    # Simulate a prior bad primary link that bypassed guards.
    with engine.begin() as conn:
        conn.execute(
            insert(album_artwork).values(
                album_id=uuid_to_blob(no_limit),
                artwork_id=uuid_to_blob(art.id),
                role="front",
                is_primary=True,
            )
        )
    assert artwork_repo.primary_conflicts_with_album(art.id, salvation) is False
    assert artwork_repo.link_album(salvation, art.id) is True
    assert artwork_repo.get_primary_for_album(salvation) == art
    assert artwork_repo.get_primary_for_album(no_limit) is None


def test_live_edition_does_not_share_studio_cover(
    artwork_repo: ArtworkRepository, engine: Engine
) -> None:
    studio = _insert_album(engine, title="The Wall", artist_name="Pink Floyd")
    live = _insert_album(engine, title="The Wall (Live)", artist_name="Pink Floyd")
    art = _make_artwork(content_hash="99" * 32)
    artwork_repo.upsert_image(art)
    assert artwork_repo.link_album(studio, art.id) is True
    assert artwork_repo.link_album(live, art.id) is False
    assert artwork_repo.get_primary_for_album(live) is None


def test_duplicate_file_inflation_does_not_steal_cover(
    artwork_repo: ArtworkRepository, engine: Engine, library_id: UUID
) -> None:
    """Physical track dumps must not outrank a real release via slot/file counts."""
    from sqlalchemy import insert

    from vaultseek.db.tables import album_artwork, tracks
    from vaultseek.db.uuid_utils import uuid_to_blob

    real = _insert_album(engine, title="Real Album", artist_name="Real Artist")
    dump = _insert_album(engine, title="Fake Dump", artist_name="Other")
    art = _make_artwork(content_hash="66" * 32)
    artwork_repo.upsert_image(art)
    with engine.begin() as conn:
        for album_id in (real, dump):
            conn.execute(
                insert(album_artwork).values(
                    album_id=uuid_to_blob(album_id),
                    artwork_id=uuid_to_blob(art.id),
                    role="front",
                    is_primary=True,
                )
            )
        for index in range(3):
            conn.execute(
                insert(tracks).values(
                    id=uuid_to_blob(generate_uuid7()),
                    library_id=uuid_to_blob(library_id),
                    album_id=uuid_to_blob(real),
                    zone="library",
                    file_path=f"C:/library/real/{index}.mp3",
                    file_name=f"{index}.mp3",
                    file_size=1,
                    file_modified="2026-07-15T00:00:00",
                    track_number=index + 1,
                    title=f"Song {index + 1}",
                    created_at="2026-07-15T00:00:00",
                    updated_at="2026-07-15T00:00:00",
                )
            )
        for index in range(20):
            conn.execute(
                insert(tracks).values(
                    id=uuid_to_blob(generate_uuid7()),
                    library_id=uuid_to_blob(library_id),
                    album_id=uuid_to_blob(dump),
                    zone="library",
                    file_path=f"C:/library/dump/{index}.mp3",
                    file_name=f"{index}.mp3",
                    file_size=1,
                    file_modified="2026-07-15T00:00:00",
                    track_number=1,
                    title="Same",
                    created_at="2026-07-15T00:00:00",
                    updated_at="2026-07-15T00:00:00",
                )
            )

    # Ambiguous dual-key primary without provenance → neither shows as known correct.
    assert artwork_repo.get_primary_for_album(real) is None
    assert artwork_repo.get_primary_for_album(dump) is None


def test_legitimate_shared_edition_cover_remains(
    artwork_repo: ArtworkRepository, engine: Engine
) -> None:
    original = _insert_album(engine, title="Salvation", artist_name="Alphaville")
    deluxe = _insert_album(engine, title="Salvation (Deluxe Version)", artist_name="Alphaville")
    art = _make_artwork(content_hash="77" * 32)
    artwork_repo.upsert_image(art)
    assert artwork_repo.link_album(original, art.id) is True
    assert artwork_repo.link_album(deluxe, art.id) is True
    assert artwork_repo.get_primary_for_album(original) == art
    assert artwork_repo.get_primary_for_album(deluxe) == art


def test_ambiguous_embedded_cross_release_is_hidden(
    artwork_repo: ArtworkRepository, engine: Engine
) -> None:
    salvation = _insert_album(engine, title="Salvation", artist_name="Alphaville")
    no_limit = _insert_album(engine, title="No Limit - EP", artist_name="2 Unlimited")
    art = _make_artwork(content_hash="88" * 32)
    art = Artwork(
        id=art.id,
        content_hash_sha256=art.content_hash_sha256,
        source="embedded_art",
        mime_type=art.mime_type,
        width=art.width,
        height=art.height,
        file_size=art.file_size,
        file_path=art.file_path,
        created_at=art.created_at,
        source_id=None,
    )
    artwork_repo.upsert_image(art)
    assert artwork_repo.link_album(no_limit, art.id) is True
    assert artwork_repo.link_album(salvation, art.id) is False
    assert artwork_repo.get_primary_for_album(salvation) is None
    assert artwork_repo.get_primary_for_album(no_limit) == art


def test_primary_prefers_artwork_whose_source_matches_the_release(
    artwork_repo: ArtworkRepository, engine: Engine
) -> None:
    from sqlalchemy import insert

    from vaultseek.db.tables import album_artwork
    from vaultseek.db.uuid_utils import uuid_to_blob

    album_id = _insert_album(
        engine, title="Alice In Chains", artist_name="Alice in Chains", mbid="release-1"
    )
    embedded = _make_artwork(content_hash="33" * 32)
    embedded = Artwork(
        id=embedded.id,
        content_hash_sha256=embedded.content_hash_sha256,
        source="embedded_art",
        mime_type=embedded.mime_type,
        width=embedded.width,
        height=embedded.height,
        file_size=embedded.file_size,
        file_path=embedded.file_path,
        created_at=datetime(2026, 9, 17, tzinfo=UTC),
        source_id=None,
    )
    canonical = _make_artwork(content_hash="44" * 32)
    canonical = Artwork(
        id=canonical.id,
        content_hash_sha256=canonical.content_hash_sha256,
        source="cover_art_archive",
        mime_type=canonical.mime_type,
        width=canonical.width,
        height=canonical.height,
        file_size=canonical.file_size,
        file_path=canonical.file_path,
        created_at=datetime(2026, 9, 16, tzinfo=UTC),
        source_id="release-1",
    )
    artwork_repo.upsert_image(embedded)
    artwork_repo.upsert_image(canonical)
    with engine.begin() as conn:
        for art in (embedded, canonical):
            conn.execute(
                insert(album_artwork).values(
                    album_id=uuid_to_blob(album_id),
                    artwork_id=uuid_to_blob(art.id),
                    role="front",
                    is_primary=True,
                )
            )

    assert artwork_repo.get_primary_for_album(album_id) == canonical
