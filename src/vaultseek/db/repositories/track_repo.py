"""TrackRepository — persistence for the `tracks` table.

Method names (`get_by_id`, `get_by_path`, `get_by_library`,
`upsert_batch`, `update_zone`) follow the `TrackRepository` protocol
documented in docs/architecture/04-service-layer.md ("Repository
Protocols") exactly.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any, TypedDict
from uuid import UUID

from sqlalchemy import Engine, Row, func, or_, select, update

from vaultseek.db.repositories.base import batch_upsert
from vaultseek.db.tables import track_artwork
from vaultseek.db.tables import tracks as tracks_table
from vaultseek.db.uuid_utils import blob_to_uuid, uuid_to_blob
from vaultseek.models.entities.track import LibraryZone, Track


class TrackReportSummary(TypedDict):
    track_count: int
    lossless_count: int
    lossy_count: int
    needs_review_count: int
    has_embedded_art_count: int
    missing_embedded_art_count: int
    average_confidence: float | None
    quality_buckets: dict[str, int]
    artists_linked: int
    albums_linked: int
    tracks_with_artist: int
    tracks_with_album: int
    tracks_with_cover: int


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

    def count_by_zone(self, library_id: UUID) -> dict[str, int]:
        """Track counts per zone for report aggregates (Phase 13)."""
        statement = (
            select(tracks_table.c.zone, func.count())
            .where(tracks_table.c.library_id == uuid_to_blob(library_id))
            .group_by(tracks_table.c.zone)
        )
        with self._engine.connect() as conn:
            rows = conn.execute(statement).all()
        return {str(zone): int(count) for zone, count in rows}

    def summarize_for_report(self, library_id: UUID) -> TrackReportSummary:
        """Single-pass aggregates for :class:`~vaultseek.services.report_service.ReportService`.

        Returns counts that would otherwise require loading every track
        row (docs/architecture/08-performance.md — reports must stream /
        aggregate, not materialize 100k entities).
        """
        lib = uuid_to_blob(library_id)
        with self._engine.connect() as conn:
            total = int(
                conn.execute(
                    select(func.count()).where(tracks_table.c.library_id == lib)
                ).scalar_one()
            )
            lossless = int(
                conn.execute(
                    select(func.count())
                    .where(tracks_table.c.library_id == lib)
                    .where(tracks_table.c.is_lossless.is_(True))
                ).scalar_one()
            )
            needs_review = int(
                conn.execute(
                    select(func.count())
                    .where(tracks_table.c.library_id == lib)
                    .where(tracks_table.c.needs_review.is_(True))
                ).scalar_one()
            )
            with_art = int(
                conn.execute(
                    select(func.count())
                    .where(tracks_table.c.library_id == lib)
                    .where(tracks_table.c.has_embedded_art.is_(True))
                ).scalar_one()
            )
            avg_conf = conn.execute(
                select(func.avg(tracks_table.c.overall_confidence)).where(
                    tracks_table.c.library_id == lib
                )
            ).scalar_one()
            artists_linked = int(
                conn.execute(
                    select(func.count(func.distinct(tracks_table.c.artist_id)))
                    .where(tracks_table.c.library_id == lib)
                    .where(tracks_table.c.artist_id.is_not(None))
                ).scalar_one()
            )
            albums_linked = int(
                conn.execute(
                    select(func.count(func.distinct(tracks_table.c.album_id)))
                    .where(tracks_table.c.library_id == lib)
                    .where(tracks_table.c.album_id.is_not(None))
                ).scalar_one()
            )
            tracks_with_artist = int(
                conn.execute(
                    select(func.count())
                    .where(tracks_table.c.library_id == lib)
                    .where(tracks_table.c.artist_id.is_not(None))
                ).scalar_one()
            )
            tracks_with_album = int(
                conn.execute(
                    select(func.count())
                    .where(tracks_table.c.library_id == lib)
                    .where(tracks_table.c.album_id.is_not(None))
                ).scalar_one()
            )
            tracks_with_cover = int(
                conn.execute(
                    select(func.count())
                    .select_from(tracks_table)
                    .join(track_artwork, track_artwork.c.track_id == tracks_table.c.id)
                    .where(tracks_table.c.library_id == lib)
                ).scalar_one()
            )
            # Quality buckets: null / low (<40) / mid / high (>=70)
            quality_rows = conn.execute(
                select(tracks_table.c.quality_score).where(tracks_table.c.library_id == lib)
            ).all()

        buckets = {"unscored": 0, "low": 0, "mid": 0, "high": 0}
        for (score,) in quality_rows:
            if score is None:
                buckets["unscored"] += 1
            elif int(score) < 40:
                buckets["low"] += 1
            elif int(score) < 70:
                buckets["mid"] += 1
            else:
                buckets["high"] += 1

        return {
            "track_count": total,
            "lossless_count": lossless,
            "lossy_count": total - lossless,
            "needs_review_count": needs_review,
            "has_embedded_art_count": with_art,
            "missing_embedded_art_count": total - with_art,
            "average_confidence": float(avg_conf) if avg_conf is not None else None,
            "quality_buckets": buckets,
            "artists_linked": artists_linked,
            "albums_linked": albums_linked,
            "tracks_with_artist": tracks_with_artist,
            "tracks_with_album": tracks_with_album,
            "tracks_with_cover": tracks_with_cover,
        }

    def confidence_distribution(self, library_id: UUID) -> dict[str, int]:
        """Bucket tracks by ``overall_confidence`` for the Dashboard.

        Buckets:
          ``unscored`` — null confidence (not yet identified)
          ``low`` — ``< 0.50``
          ``fair`` — ``0.50`` inclusive to ``< 0.90``
          ``high`` — ``>= 0.90`` (auto-approve territory)
          ``flagged`` — ``needs_review`` is true (may overlap other buckets)
        """
        lib = uuid_to_blob(library_id)
        with self._engine.connect() as conn:
            rows = conn.execute(
                select(
                    tracks_table.c.overall_confidence,
                    tracks_table.c.needs_review,
                ).where(tracks_table.c.library_id == lib)
            ).all()

        buckets = {"unscored": 0, "low": 0, "fair": 0, "high": 0, "flagged": 0}
        for confidence, needs_review in rows:
            if needs_review:
                buckets["flagged"] += 1
            if confidence is None:
                buckets["unscored"] += 1
            elif float(confidence) < 0.50:
                buckets["low"] += 1
            elif float(confidence) < 0.90:
                buckets["fair"] += 1
            else:
                buckets["high"] += 1
        return buckets

    def list_by_artist(
        self,
        library_id: UUID,
        artist_id: UUID,
        *,
        limit: int = 500,
        offset: int = 0,
    ) -> Sequence[Track]:
        statement = (
            select(tracks_table)
            .where(tracks_table.c.library_id == uuid_to_blob(library_id))
            .where(tracks_table.c.artist_id == uuid_to_blob(artist_id))
            .order_by(tracks_table.c.album_id, tracks_table.c.track_number, tracks_table.c.file_name)
            .offset(offset)
            .limit(limit)
        )
        with self._engine.connect() as conn:
            rows = conn.execute(statement).all()
        return [_from_row(row) for row in rows]

    def list_by_album(
        self,
        library_id: UUID,
        album_id: UUID,
        *,
        limit: int = 500,
        offset: int = 0,
    ) -> Sequence[Track]:
        statement = (
            select(tracks_table)
            .where(tracks_table.c.library_id == uuid_to_blob(library_id))
            .where(tracks_table.c.album_id == uuid_to_blob(album_id))
            .order_by(tracks_table.c.disc_number, tracks_table.c.track_number, tracks_table.c.file_name)
            .offset(offset)
            .limit(limit)
        )
        with self._engine.connect() as conn:
            rows = conn.execute(statement).all()
        return [_from_row(row) for row in rows]

    def list_by_path_prefix(
        self,
        library_id: UUID,
        path_prefix: str,
        *,
        zone: LibraryZone | None = None,
        limit: int = 500,
        offset: int = 0,
    ) -> Sequence[Track]:
        """Tracks under ``path_prefix`` (folder browse; avoids sibling-prefix matches)."""
        prefix = path_prefix.rstrip("\\/")
        statement = (
            select(tracks_table)
            .where(tracks_table.c.library_id == uuid_to_blob(library_id))
            .where(
                or_(
                    tracks_table.c.file_path.startswith(prefix + "\\"),
                    tracks_table.c.file_path.startswith(prefix + "/"),
                    tracks_table.c.file_path == prefix,
                )
            )
            .order_by(tracks_table.c.file_path)
            .offset(offset)
            .limit(limit)
        )
        if zone is not None:
            statement = statement.where(tracks_table.c.zone == zone.value)
        with self._engine.connect() as conn:
            rows = conn.execute(statement).all()
        return [_from_row(row) for row in rows]

    def list_paths_for_library(
        self, library_id: UUID, *, limit: int = 5000
    ) -> list[tuple[str, str]]:
        """Lightweight ``(zone, file_path)`` rows for building the folder tree."""
        statement = (
            select(tracks_table.c.zone, tracks_table.c.file_path)
            .where(tracks_table.c.library_id == uuid_to_blob(library_id))
            .order_by(tracks_table.c.file_path)
            .limit(limit)
        )
        with self._engine.connect() as conn:
            rows = conn.execute(statement).all()
        return [(str(zone), str(path)) for zone, path in rows]

    def update_zone(self, track_id: UUID, zone: LibraryZone) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                update(tracks_table)
                .where(tracks_table.c.id == uuid_to_blob(track_id))
                .values(zone=zone.value)
            )

    @staticmethod
    def to_row(track: Track) -> dict[str, object]:
        """Public row-shape builder for callers (e.g. `ScannerWorker`)
        that submit `tracks` writes via `DatabaseWriter` instead of
        this repository's own `upsert_batch`."""
        return _to_row(track)


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
