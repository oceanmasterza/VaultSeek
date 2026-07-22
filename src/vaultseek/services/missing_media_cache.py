"""In-memory cache of the last missing-media scan (no MusicBrainz on dashboard refresh)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class MissingMediaSnapshot:
    """Result of an explicit missing-media scan for one library."""

    missing_tracks: int
    incomplete_albums: int
    albums_scanned: int
    complete_albums: int
    scanned_at: datetime


_store: dict[UUID, MissingMediaSnapshot] = {}


def record_scan(
    library_id: UUID,
    *,
    missing_tracks: int,
    incomplete_albums: int,
    albums_scanned: int,
    complete_albums: int,
) -> MissingMediaSnapshot:
    snapshot = MissingMediaSnapshot(
        missing_tracks=missing_tracks,
        incomplete_albums=incomplete_albums,
        albums_scanned=albums_scanned,
        complete_albums=complete_albums,
        scanned_at=datetime.now(UTC),
    )
    _store[library_id] = snapshot
    return snapshot


def get_snapshot(library_id: UUID) -> MissingMediaSnapshot | None:
    return _store.get(library_id)


def clear(library_id: UUID) -> None:
    _store.pop(library_id, None)
