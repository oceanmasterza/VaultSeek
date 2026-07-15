"""TrackRepository — persistence for the `tracks` table.

Method names (`get_by_id`, `get_by_path`, `get_by_library`,
`upsert_batch`, `update_zone`) follow the `TrackRepository` protocol
documented in docs/architecture/04-service-layer.md ("Repository
Protocols") exactly.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Engine, Row, select, update

from musicvault.db.repositories.base import batch_upsert
from musicvault.db.tables import tracks as tracks_table
from musicvault.db.uuid_utils import blob_to_uuid, uuid_to_blob
from musicvault.models.entities.track import LibraryZone, Track


class TrackRepository:
    """Reads and writes `Track` entities against the `tracks` table."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def upsert(self, track: Track) -> None:
        """Persist a single track (insert, or overwrite if its id already exists)."""
        self.upsert_batch([track])

    def upsert_batch(self, tracks: Sequence[Track]) -> int:
        """Persist many tracks in one transaction. Returns the number of rows upserted."""
        rows = [_to_row(track) for track in tracks]
        with self._engine.begin() as conn:
            batch_upsert(conn, tracks_table, rows, conflict_columns=["id"])
        return len(rows)

    def get_by_id(self, track_id: UUID) -> Track | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                select(tracks_table).where(tracks_table.c.id == uuid_to_blob(track_id))
            ).first()
        return _from_row(row) if row is not None else None

    def get_by_path(self, file_path: str) -> Track | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                select(tracks_table).where(tracks_table.c.file_path == file_path)
            ).first()
        return _from_row(row) if row is not None else None

    def get_by_library(
        self,
        library_id: UUID,
        zone: LibraryZone | None = None,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> Sequence[Track]:
        statement = select(tracks_table).where(
            tracks_table.c.library_id == uuid_to_blob(library_id)
        )
        if zone is not None:
            statement = statement.where(tracks_table.c.zone == zone.value)
        statement = statement.offset(offset).limit(limit)

        with self._engine.connect() as conn:
            rows = conn.execute(statement).all()
        return [_from_row(row) for row in rows]

    def update_zone(self, track_id: UUID, zone: LibraryZone) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                update(tracks_table)
                .where(tracks_table.c.id == uuid_to_blob(track_id))
                .values(zone=zone.value)
            )


def _to_row(track: Track) -> dict[str, object]:
    return {
        "id": uuid_to_blob(track.id),
        "library_id": uuid_to_blob(track.library_id),
        "album_id": uuid_to_blob(track.album_id) if track.album_id else None,
        "artist_id": uuid_to_blob(track.artist_id) if track.artist_id else None,
        "zone": track.zone.value,
        "file_path": track.file_path,
        "file_name": track.file_name,
        "file_size": track.file_size,
        "file_modified": track.file_modified.isoformat(),
        "title": track.title,
        "track_number": track.track_number,
        "disc_number": track.disc_number,
        "duration_ms": track.duration_ms,
        "bitrate": track.bitrate,
        "bit_depth": track.bit_depth,
        "sample_rate": track.sample_rate,
        "channels": track.channels,
        "codec": track.codec,
        "is_lossless": track.is_lossless,
        "quality_score": track.quality_score,
        "mb_recording_id": track.mb_recording_id,
        "composer": track.composer,
        "genre": track.genre,
        "year": track.year,
        "has_embedded_art": track.has_embedded_art,
        "is_corrupt": track.is_corrupt,
        "overall_confidence": track.overall_confidence,
        "needs_review": track.needs_review,
        "created_at": track.created_at.isoformat(),
        "updated_at": track.updated_at.isoformat(),
    }


def _from_row(row: Row[Any]) -> Track:
    return Track(
        id=blob_to_uuid(row.id),
        library_id=blob_to_uuid(row.library_id),
        zone=LibraryZone(row.zone),
        file_path=row.file_path,
        file_name=row.file_name,
        file_size=row.file_size,
        file_modified=datetime.fromisoformat(row.file_modified),
        created_at=datetime.fromisoformat(row.created_at),
        updated_at=datetime.fromisoformat(row.updated_at),
        album_id=blob_to_uuid(row.album_id) if row.album_id else None,
        artist_id=blob_to_uuid(row.artist_id) if row.artist_id else None,
        title=row.title,
        track_number=row.track_number,
        disc_number=row.disc_number,
        duration_ms=row.duration_ms,
        bitrate=row.bitrate,
        bit_depth=row.bit_depth,
        sample_rate=row.sample_rate,
        channels=row.channels,
        codec=row.codec,
        is_lossless=bool(row.is_lossless),
        quality_score=row.quality_score,
        mb_recording_id=row.mb_recording_id,
        composer=row.composer,
        genre=row.genre,
        year=row.year,
        has_embedded_art=bool(row.has_embedded_art),
        is_corrupt=bool(row.is_corrupt),
        overall_confidence=row.overall_confidence,
        needs_review=bool(row.needs_review),
    )
