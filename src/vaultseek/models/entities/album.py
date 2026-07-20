"""Album entity — mirrors the `albums` table column-for-column
(see docs/architecture/03-database-schema.md, "albums")."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class Album:
    """A single album/release, persisted in the `albums` table."""

    id: UUID
    title: str
    sort_title: str
    created_at: datetime
    updated_at: datetime
    album_artist_id: UUID | None = None
    year: int | None = None
    mbid: str | None = None
    release_group_mbid: str | None = None
    discogs_id: str | None = None
    type: str | None = None
    genre: str | None = None
    disc_count: int = 1
    track_count: int = 0
    is_compilation: bool = False
