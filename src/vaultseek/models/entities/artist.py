"""Artist entity — mirrors the `artists` table column-for-column
(see docs/architecture/03-database-schema.md, "artists")."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class Artist:
    """A single artist, persisted in the `artists` table."""

    id: UUID
    name: str
    sort_name: str
    created_at: datetime
    updated_at: datetime
    mbid: str | None = None
    discogs_id: str | None = None
    type: str | None = None
    country: str | None = None
