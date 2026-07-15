"""ArtistRepository — persistence for the `artists` table."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Engine, Row, select

from musicvault.db.repositories.base import batch_upsert
from musicvault.db.tables import artists as artists_table
from musicvault.db.uuid_utils import blob_to_uuid, uuid_to_blob
from musicvault.models.entities.artist import Artist


class ArtistRepository:
    """Reads and writes `Artist` entities against the `artists` table."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def create(self, artist: Artist) -> None:
        """Persist a single artist (insert, or overwrite if its id already exists)."""
        self.batch_create([artist])

    def batch_create(self, artists: Sequence[Artist]) -> None:
        """Persist many artists in one transaction — see
        :func:`musicvault.db.repositories.base.batch_upsert`."""
        rows = [_to_row(artist) for artist in artists]
        with self._engine.begin() as conn:
            batch_upsert(conn, artists_table, rows, conflict_columns=["id"])

    def get(self, artist_id: UUID) -> Artist | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                select(artists_table).where(artists_table.c.id == uuid_to_blob(artist_id))
            ).first()
        return _from_row(row) if row is not None else None

    def get_by_mbid(self, mbid: str) -> Artist | None:
        with self._engine.connect() as conn:
            row = conn.execute(select(artists_table).where(artists_table.c.mbid == mbid)).first()
        return _from_row(row) if row is not None else None

    def list_by_name(self, name: str) -> list[Artist]:
        """All artists with this exact display name (not unique — e.g.
        two different "The Band" entries from different eras/regions)."""
        with self._engine.connect() as conn:
            rows = conn.execute(select(artists_table).where(artists_table.c.name == name)).all()
        return [_from_row(row) for row in rows]


def _to_row(artist: Artist) -> dict[str, object]:
    return {
        "id": uuid_to_blob(artist.id),
        "name": artist.name,
        "sort_name": artist.sort_name,
        "mbid": artist.mbid,
        "discogs_id": artist.discogs_id,
        "type": artist.type,
        "country": artist.country,
        "created_at": artist.created_at.isoformat(),
        "updated_at": artist.updated_at.isoformat(),
    }


def _from_row(row: Row[Any]) -> Artist:
    return Artist(
        id=blob_to_uuid(row.id),
        name=row.name,
        sort_name=row.sort_name,
        created_at=datetime.fromisoformat(row.created_at),
        updated_at=datetime.fromisoformat(row.updated_at),
        mbid=row.mbid,
        discogs_id=row.discogs_id,
        type=row.type,
        country=row.country,
    )
