"""Track entity — a single audio file tracked by MusicVault.

Mirrors the `tracks` table column-for-column (see
docs/architecture/03-database-schema.md, "tracks"). This is the
*richer* domain model deferred from Phase 2 (which only pulled forward
`Job`, `ReviewItem`, `Rule`, and `FileIdentity` as minimal repository
return types) — see docs/architecture/07-roadmap.md, Phase 3.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class LibraryZone(StrEnum):
    """A track's position in the Incoming → Staging → Library → Archive
    pipeline (see docs/architecture/01-overview.md, "Core Data Flow").
    The state machine that moves tracks between zones is
    :class:`~musicvault.models.services.organize_engine.OrganizeEngine`,
    which is Phase 10 scope — this enum only needs to exist now because
    it is one of :class:`Track`'s fields.
    """

    INCOMING = "incoming"
    STAGING = "staging"
    LIBRARY = "library"
    ARCHIVE = "archive"


@dataclass(frozen=True, slots=True)
class Track:
    """A single audio file, persisted in the `tracks` table."""

    id: UUID
    library_id: UUID
    zone: LibraryZone
    file_path: str
    file_name: str
    file_size: int
    file_modified: datetime
    created_at: datetime
    updated_at: datetime
    album_id: UUID | None = None
    artist_id: UUID | None = None
    title: str | None = None
    track_number: int | None = None
    disc_number: int = 1
    duration_ms: int | None = None
    bitrate: int | None = None
    bit_depth: int | None = None
    sample_rate: int | None = None
    channels: int | None = None
    codec: str | None = None
    is_lossless: bool = False
    quality_score: int | None = None
    mb_recording_id: str | None = None
    composer: str | None = None
    genre: str | None = None
    year: int | None = None
    has_embedded_art: bool = False
    is_corrupt: bool = False
    overall_confidence: float | None = None
    needs_review: bool = False
