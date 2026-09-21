"""AlbumRepository — persistence for the `albums` table."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Engine, Row, and_, case, delete, exists, func, or_, select, update

from vaultseek.core.exceptions import OperationError
from vaultseek.db import tables
from vaultseek.db.repositories.artwork_repo import ArtworkRepository
from vaultseek.db.repositories.base import batch_upsert
from vaultseek.db.tables import album_artwork, artists
from vaultseek.db.tables import albums as albums_table
from vaultseek.db.tables import tracks as tracks_table
from vaultseek.db.uuid_utils import blob_to_uuid, uuid_to_blob
from vaultseek.models.dto.browse_dto import AlbumBrowseRow
from vaultseek.models.entities.album import Album


class AlbumRepository:
    """Reads and writes `Album` entities against the `albums` table."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def create(self, album: Album) -> None:
        """Persist a single album (insert, or overwrite if its id already exists)."""
        self.batch_create([album])

    def batch_create(self, albums: Sequence[Album]) -> None:
        """Persist many albums in one transaction — see
        :func:`vaultseek.db.repositories.base.batch_upsert`."""
        rows = [_to_row(album) for album in albums]
        with self._engine.begin() as conn:
            batch_upsert(conn, albums_table, rows, conflict_columns=["id"])

    def count_tracks(self, library_id: UUID, album_ids: Sequence[UUID]) -> int:
        with self._engine.connect() as conn:
            return int(
                conn.execute(
                    select(func.count())
                    .select_from(tracks_table)
                    .where(
                        tracks_table.c.library_id == uuid_to_blob(library_id),
                        tracks_table.c.album_id.in_([uuid_to_blob(aid) for aid in album_ids]),
                    )
                ).scalar_one()
            )

    @contextmanager
    def removal(self, library_id: UUID, album_id: UUID) -> Iterator[list[str]]:
        """Lock a deletion plan; commit metadata removal only after files are removed.

        Filesystem failure rolls back metadata, allowing a retry. Already recycled
        files remain recoverable from the Recycle Bin.
        """
        lib, aid = uuid_to_blob(library_id), uuid_to_blob(album_id)
        with self._engine.connect() as conn:
            conn.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                album = conn.execute(select(albums_table).where(albums_table.c.id == aid)).first()
                if album is None:
                    raise OperationError("This album no longer exists. Refresh Albums.")
                busy = conn.execute(
                    select(tables.jobs.c.id)
                    .where(
                        tables.jobs.c.library_id == lib,
                        tables.jobs.c.status.in_(["pending", "running", "retry"]),
                    )
                    .limit(1)
                ).first()
                acquiring = conn.execute(
                    select(tables.acquisition_jobs.c.id)
                    .where(
                        tables.acquisition_jobs.c.library_id == lib,
                        tables.acquisition_jobs.c.album == album.title,
                        tables.acquisition_jobs.c.state.not_in(["completed", "cancelled"]),
                    )
                    .limit(1)
                ).first()
                if busy or acquiring:
                    raise OperationError(
                        "Wait for library processing to finish and cancel this album's "
                        "unfinished downloads in Wishlist before deleting it."
                    )
                rows = conn.execute(
                    select(tracks_table.c.id, tracks_table.c.file_path).where(
                        tracks_table.c.library_id == lib,
                        tracks_table.c.album_id == aid,
                    )
                ).all()
                ids = [row.id for row in rows]
                paths = [str(row.file_path) for row in rows]
                if not ids:
                    raise OperationError("This album has no tracks in the selected library.")
                shared = conn.execute(
                    select(tracks_table.c.id)
                    .where(
                        tracks_table.c.file_path.collate("NOCASE").in_(paths),
                        tracks_table.c.id.not_in(ids),
                    )
                    .limit(1)
                ).first()
                if shared:
                    raise OperationError(
                        "A selected file is also registered to another album or library."
                    )
                groups = list(
                    conn.execute(
                        select(tables.duplicate_members.c.group_id).where(
                            tables.duplicate_members.c.track_id.in_(ids)
                        )
                    ).scalars()
                )
                for table in (
                    tables.file_identity,
                    tables.metadata_confidence,
                    tables.track_artwork,
                    tables.duplicate_members,
                    tables.review_items,
                ):
                    conn.execute(delete(table).where(table.c.track_id.in_(ids)))
                conn.execute(
                    update(tables.change_history)
                    .where(tables.change_history.c.track_id.in_(ids))
                    .values(track_id=None)
                )
                conn.execute(
                    update(tables.duplicate_groups)
                    .where(tables.duplicate_groups.c.best_track_id.in_(ids))
                    .values(best_track_id=None)
                )
                conn.execute(delete(tracks_table).where(tracks_table.c.id.in_(ids)))
                for group in set(groups):
                    count = conn.execute(
                        select(func.count())
                        .select_from(tables.duplicate_members)
                        .where(tables.duplicate_members.c.group_id == group)
                    ).scalar_one()
                    conn.execute(
                        update(tables.duplicate_groups)
                        .where(tables.duplicate_groups.c.id == group)
                        .values(track_count=count)
                    )
                if not conn.execute(
                    select(tracks_table.c.id).where(tracks_table.c.album_id == aid).limit(1)
                ).first():
                    conn.execute(
                        delete(tables.album_artwork).where(tables.album_artwork.c.album_id == aid)
                    )
                    conn.execute(
                        delete(tables.review_items).where(tables.review_items.c.album_id == aid)
                    )
                    conn.execute(delete(albums_table).where(albums_table.c.id == aid))
                yield paths
                conn.commit()
            except BaseException:
                conn.rollback()
                raise

    def get(self, album_id: UUID) -> Album | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                select(albums_table).where(albums_table.c.id == uuid_to_blob(album_id))
            ).first()
        return _from_row(row) if row is not None else None

    def get_by_mbid(self, mbid: str) -> Album | None:
        with self._engine.connect() as conn:
            row = conn.execute(select(albums_table).where(albums_table.c.mbid == mbid)).first()
        return _from_row(row) if row is not None else None

    def list_by_artist(self, album_artist_id: UUID) -> list[Album]:
        statement = select(albums_table).where(
            albums_table.c.album_artist_id == uuid_to_blob(album_artist_id)
        )
        with self._engine.connect() as conn:
            rows = conn.execute(statement).all()
        return [_from_row(row) for row in rows]

    def list_for_library(
        self,
        library_id: UUID,
        *,
        artist_id: UUID | None = None,
        query: str | None = None,
        limit: int = 500,
        offset: int = 0,
    ) -> list[AlbumBrowseRow]:
        """Albums linked to tracks in this library, with artist name and cover flag."""
        lib = uuid_to_blob(library_id)
        # Distinct disc+number+title slots, not every physical copy. Matches
        # release_slot_key: nonpositive / missing numbers each keep their own slot.
        release_slot = case(
            (
                and_(
                    tracks_table.c.track_number.is_not(None),
                    tracks_table.c.track_number > 0,
                ),
                func.printf(
                    "%d:%d:%s",
                    tracks_table.c.disc_number,
                    tracks_table.c.track_number,
                    func.lower(func.coalesce(tracks_table.c.title, "")),
                ),
            ),
            else_=func.hex(tracks_table.c.id),
        )
        present_count = func.count(func.distinct(release_slot)).label("present_count")
        has_cover = exists(
            select(album_artwork.c.artwork_id)
            .where(album_artwork.c.album_id == albums_table.c.id)
            .where(album_artwork.c.is_primary.is_(True))
        ).label("has_cover")
        statement = (
            select(
                albums_table.c.id,
                albums_table.c.title,
                albums_table.c.sort_title,
                albums_table.c.album_artist_id,
                albums_table.c.year,
                albums_table.c.mbid,
                albums_table.c.track_count.label("expected_track_count"),
                artists.c.name.label("artist_name"),
                present_count,
                has_cover,
            )
            .join(tracks_table, tracks_table.c.album_id == albums_table.c.id)
            .outerjoin(artists, artists.c.id == albums_table.c.album_artist_id)
            .where(tracks_table.c.library_id == lib)
            .group_by(
                albums_table.c.id,
                albums_table.c.title,
                albums_table.c.sort_title,
                albums_table.c.album_artist_id,
                albums_table.c.year,
                albums_table.c.mbid,
                albums_table.c.track_count,
                artists.c.name,
            )
            .order_by(artists.c.name, albums_table.c.year, albums_table.c.sort_title)
            .offset(offset)
            .limit(limit)
        )
        if artist_id is not None:
            statement = statement.where(albums_table.c.album_artist_id == uuid_to_blob(artist_id))
        if query:
            like = f"%{query}%"
            statement = statement.where(
                or_(albums_table.c.title.ilike(like), artists.c.name.ilike(like))
            )
        with self._engine.connect() as conn:
            rows = conn.execute(statement).all()
        artwork_repo = ArtworkRepository(self._engine)
        results: list[AlbumBrowseRow] = []
        for row in rows:
            album_id = blob_to_uuid(row.id)
            cover_ok = (
                bool(row.has_cover) and artwork_repo.get_primary_for_album(album_id) is not None
            )
            results.append(
                AlbumBrowseRow(
                    album_id=album_id,
                    title=row.title,
                    sort_title=row.sort_title,
                    artist_name=row.artist_name,
                    artist_id=blob_to_uuid(row.album_artist_id) if row.album_artist_id else None,
                    year=row.year,
                    track_count=int(row.present_count),
                    has_cover=cover_ok,
                    mbid=row.mbid,
                    expected_track_count=(
                        int(row.expected_track_count)
                        if row.expected_track_count not in (None, 0)
                        else None
                    ),
                )
            )
        return results


def _to_row(album: Album) -> dict[str, object]:
    return {
        "id": uuid_to_blob(album.id),
        "title": album.title,
        "sort_title": album.sort_title,
        "album_artist_id": (uuid_to_blob(album.album_artist_id) if album.album_artist_id else None),
        "year": album.year,
        "mbid": album.mbid,
        "release_group_mbid": album.release_group_mbid,
        "discogs_id": album.discogs_id,
        "type": album.type,
        "genre": album.genre,
        "disc_count": album.disc_count,
        "track_count": album.track_count,
        "is_compilation": album.is_compilation,
        "created_at": album.created_at.isoformat(),
        "updated_at": album.updated_at.isoformat(),
    }


def _from_row(row: Row[Any]) -> Album:
    return Album(
        id=blob_to_uuid(row.id),
        title=row.title,
        sort_title=row.sort_title,
        created_at=datetime.fromisoformat(row.created_at),
        updated_at=datetime.fromisoformat(row.updated_at),
        album_artist_id=blob_to_uuid(row.album_artist_id) if row.album_artist_id else None,
        year=row.year,
        mbid=row.mbid,
        release_group_mbid=row.release_group_mbid,
        discogs_id=row.discogs_id,
        type=row.type,
        genre=row.genre,
        disc_count=row.disc_count,
        track_count=row.track_count,
        is_compilation=bool(row.is_compilation),
    )
