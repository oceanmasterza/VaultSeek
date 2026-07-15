"""AlbumRepository — persistence for the `albums` table."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Engine, Row, select

from musicvault.db.repositories.base import batch_upsert
from musicvault.db.tables import albums as albums_table
from musicvault.db.uuid_utils import blob_to_uuid, uuid_to_blob
from musicvault.models.entities.album import Album


class AlbumRepository:
    """Reads and writes `Album` entities against the `albums` table."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def create(self, album: Album) -> None:
        """Persist a single album (insert, or overwrite if its id already exists)."""
        self.batch_create([album])

    def batch_create(self, albums: Sequence[Album]) -> None:
        """Persist many albums in one transaction — see
        :func:`musicvault.db.repositories.base.batch_upsert`."""
        rows = [_to_row(album) for album in albums]
        with self._engine.begin() as conn:
            batch_upsert(conn, albums_table, rows, conflict_columns=["id"])

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
