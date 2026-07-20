"""Browse query tests for artists / albums / tracks / artwork."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Engine, insert

from vaultseek.db.repositories.album_repo import AlbumRepository
from vaultseek.db.repositories.artist_repo import ArtistRepository
from vaultseek.db.repositories.artwork_repo import ArtworkRepository
from vaultseek.db.repositories.track_repo import TrackRepository
from vaultseek.db.tables import albums
from vaultseek.db.uuid_utils import generate_uuid7, uuid_to_blob
from vaultseek.models.entities.artist import Artist
from vaultseek.models.entities.artwork import Artwork
from vaultseek.models.entities.track import LibraryZone, Track

_NOW = datetime(2026, 7, 19, tzinfo=UTC)


def _track(
    library_id: UUID,
    *,
    path: str,
    artist_id: UUID | None = None,
    album_id: UUID | None = None,
    zone: LibraryZone = LibraryZone.LIBRARY,
) -> Track:
    return Track(
        id=generate_uuid7(),
        library_id=library_id,
        zone=zone,
        file_path=path,
        file_name=path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1],
        file_size=1,
        file_modified=_NOW,
        created_at=_NOW,
        updated_at=_NOW,
        artist_id=artist_id,
        album_id=album_id,
        title="Song",
    )


def test_artist_list_for_library_counts_tracks_and_albums(
    engine: Engine, library_id: UUID
) -> None:
    artists = ArtistRepository(engine)
    tracks = TrackRepository(engine)
    artist = Artist(
        id=generate_uuid7(),
        name="Radiohead",
        sort_name="Radiohead",
        created_at=_NOW,
        updated_at=_NOW,
    )
    artists.create(artist)
    album_a = generate_uuid7()
    album_b = generate_uuid7()
    with engine.begin() as conn:
        for alb_id, title in ((album_a, "OK Computer"), (album_b, "Kid A")):
            conn.execute(
                insert(albums).values(
                    id=uuid_to_blob(alb_id),
                    title=title,
                    sort_title=title,
                    album_artist_id=uuid_to_blob(artist.id),
                    created_at=_NOW.isoformat(),
                    updated_at=_NOW.isoformat(),
                )
            )
    tracks.upsert(_track(library_id, path="C:/library/Radiohead/OK/01.flac", artist_id=artist.id, album_id=album_a))
    tracks.upsert(_track(library_id, path="C:/library/Radiohead/OK/02.flac", artist_id=artist.id, album_id=album_a))
    tracks.upsert(_track(library_id, path="C:/library/Radiohead/KidA/01.flac", artist_id=artist.id, album_id=album_b))

    rows = artists.list_for_library(library_id)
    assert len(rows) == 1
    assert rows[0].name == "Radiohead"
    assert rows[0].track_count == 3
    assert rows[0].album_count == 2


def test_album_list_for_library_and_track_list_by_album(
    engine: Engine, library_id: UUID, artist_id: UUID
) -> None:
    albums_repo = AlbumRepository(engine)
    tracks = TrackRepository(engine)
    album_id = generate_uuid7()
    with engine.begin() as conn:
        conn.execute(
            insert(albums).values(
                id=uuid_to_blob(album_id),
                title="OK Computer",
                sort_title="OK Computer",
                album_artist_id=uuid_to_blob(artist_id),
                year=1997,
                created_at=_NOW.isoformat(),
                updated_at=_NOW.isoformat(),
            )
        )
    tracks.upsert(
        _track(
            library_id,
            path="C:/library/A/OK/01.flac",
            artist_id=artist_id,
            album_id=album_id,
        )
    )

    rows = albums_repo.list_for_library(library_id)
    assert len(rows) == 1
    assert rows[0].title == "OK Computer"
    assert rows[0].year == 1997
    assert rows[0].track_count == 1
    assert rows[0].has_cover is False

    listed = tracks.list_by_album(library_id, album_id)
    assert len(listed) == 1
    assert listed[0].album_id == album_id


def test_list_by_path_prefix_and_artwork_browse(
    engine: Engine, library_id: UUID, artist_id: UUID
) -> None:
    tracks = TrackRepository(engine)
    artwork = ArtworkRepository(engine)
    album_id = generate_uuid7()
    with engine.begin() as conn:
        conn.execute(
            insert(albums).values(
                id=uuid_to_blob(album_id),
                title="OK Computer",
                sort_title="OK Computer",
                album_artist_id=uuid_to_blob(artist_id),
                created_at=_NOW.isoformat(),
                updated_at=_NOW.isoformat(),
            )
        )
    tracks.upsert(
        _track(
            library_id,
            path=r"C:\library\Radiohead\OK Computer\01.flac",
            artist_id=artist_id,
            album_id=album_id,
        )
    )
    tracks.upsert(
        _track(
            library_id,
            path=r"C:\library\RadioheadExtra\x.flac",
            artist_id=artist_id,
            album_id=album_id,
        )
    )

    under = tracks.list_by_path_prefix(library_id, r"C:\library\Radiohead")
    assert len(under) == 1
    assert "OK Computer" in under[0].file_path

    paths = tracks.list_paths_for_library(library_id)
    assert len(paths) == 2

    # Missing cover
    browse = artwork.list_browse_for_library(library_id)
    assert len(browse) == 1
    assert browse[0].status == "missing"

    art = Artwork(
        id=generate_uuid7(),
        content_hash_sha256="ab" * 32,
        source="embedded_art",
        mime_type="image/jpeg",
        width=600,
        height=600,
        file_size=10,
        file_path="C:/cache/ab.jpg",
        created_at=_NOW,
    )
    art_id = artwork.upsert_image(art)
    artwork.link_album(album_id, art_id)
    browse2 = artwork.list_browse_for_library(library_id)
    assert browse2[0].status == "ok"
    assert browse2[0].cover_source == "embedded_art"
