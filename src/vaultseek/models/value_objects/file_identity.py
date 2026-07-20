"""FileIdentity value object — a track's persisted hash and fingerprint.

Mirrors the `file_identity` table (see
docs/architecture/03-database-schema.md, "File Identity (Fingerprint
Persistence)"). A value object rather than an entity: it has no identity
of its own beyond the track it describes, and `track_id` doubles as its
natural key. Pulled forward from Phase 3 for the same reason as
:class:`~vaultseek.models.entities.job.Job` — it is the return type
:class:`~vaultseek.db.repositories.file_identity_repo.FileIdentityRepository`
needs now.

The "skip logic" this table exists for — comparing `file_size` +
`file_modified` against the track's current values to decide whether the
hash/fingerprint workers can be skipped — is implemented on
:class:`FileIdentity` itself (:meth:`FileIdentity.matches_current_file`)
since it is a pure, dependency-free calculation, not I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class FileIdentity:
    """A track's computed content hash and audio fingerprint."""

    track_id: UUID
    content_hash_sha256: str
    file_size: int
    file_modified: datetime
    fingerprint_data: bytes | None = None
    fingerprint_duration: float | None = None
    fingerprint_hash: str | None = None
    acoustid_id: str | None = None
    acoustid_score: float | None = None
    hash_computed_at: datetime | None = None
    fingerprint_computed_at: datetime | None = None

    def matches_current_file(self, *, file_size: int, file_modified: datetime) -> bool:
        """Whether the file this identity was computed for is unchanged.

        If both match, the hash and fingerprint workers can skip
        recomputation entirely — see the schema document's "Skip logic".
        """
        return self.file_size == file_size and self.file_modified == file_modified
