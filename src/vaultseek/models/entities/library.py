"""Library entity — a configured music library and its zone roots.

Mirrors the `libraries` table column-for-column (see
docs/architecture/03-database-schema.md, "libraries"). Created in
Phase 10 — earlier phases only needed `library_id` foreign keys, so
libraries were inserted directly via Core in tests; the organizer and
watch-folder service are the first production consumers that must read
zone paths, `watch_enabled`, and `auto_approve_threshold`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from vaultseek.models.entities.track import LibraryZone


@dataclass(frozen=True, slots=True)
class Library:
    """A configured library, persisted in the `libraries` table."""

    id: UUID
    name: str
    incoming_path: str
    staging_path: str
    library_path: str
    archive_path: str
    created_at: datetime
    updated_at: datetime
    watch_enabled: bool = False
    auto_approve_threshold: float = 0.90

    def zone_root(self, zone: LibraryZone) -> str:
        """The filesystem root configured for ``zone``."""
        match zone:
            case LibraryZone.INCOMING:
                return self.incoming_path
            case LibraryZone.STAGING:
                return self.staging_path
            case LibraryZone.LIBRARY:
                return self.library_path
            case LibraryZone.ARCHIVE:
                return self.archive_path
