"""Artwork entity — one stored album-art image.

The v1 column-level design of the `artwork` / `track_artwork` /
`album_artwork` tables was lost when the v2 schema document superseded
it (see the "Documentation gap" note in
docs/architecture/03-database-schema.md); only the ER-diagram
relationships survived. This is Phase 11's replacement design, now
recorded in that document:

- ``artwork`` stores one row per *unique image* (deduplicated by
  ``content_hash_sha256``); the bytes live on disk under the app cache
  directory, not as DB blobs, keeping the database small.
- ``track_artwork`` / ``album_artwork`` are link tables carrying a
  ``role`` (only ``front`` is used today) and an ``is_primary`` flag.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class ArtworkRole(StrEnum):
    """How an image relates to a track/album. Only fronts are fetched
    today; the vocabulary can grow (back, disc, booklet) without a
    schema change."""

    FRONT = "front"


@dataclass(frozen=True, slots=True)
class Artwork:
    """A single stored image, persisted in the `artwork` table."""

    id: UUID
    content_hash_sha256: str
    source: str
    mime_type: str
    width: int
    height: int
    file_size: int
    file_path: str
    created_at: datetime
    source_id: str | None = None
