"""DuplicateGroup / DuplicateMember entities — duplicate detection storage.

Mirror the `duplicate_groups` and `duplicate_members` tables
column-for-column (see docs/architecture/03-database-schema.md,
"Duplicate Detection"). Created in Phase 9 alongside
:class:`~vaultseek.models.services.duplicate_matcher.DuplicateMatcher`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class MatchType(StrEnum):
    """How the members of a duplicate group were matched.

    ``FUZZY`` is part of the documented vocabulary but has no
    implementation yet (no documented similarity thresholds) — only the
    three exact-key tiers below are produced by Phase 9.
    """

    HASH = "hash"
    FINGERPRINT = "fingerprint"
    MBID = "mbid"
    FUZZY = "fuzzy"


class GroupStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"
    IGNORED = "ignored"


class GroupResolution(StrEnum):
    KEPT_BEST = "kept_best"
    ARCHIVED = "archived"
    MANUAL = "manual"


@dataclass(frozen=True, slots=True)
class DuplicateGroup:
    """A set of tracks detected as duplicates, persisted in `duplicate_groups`."""

    id: UUID
    library_id: UUID
    match_type: MatchType
    match_confidence: float
    track_count: int
    detected_at: datetime
    best_track_id: UUID | None = None
    status: GroupStatus = GroupStatus.OPEN
    resolution: GroupResolution | None = None


@dataclass(frozen=True, slots=True)
class DuplicateMember:
    """One track's membership in a duplicate group (`duplicate_members`)."""

    group_id: UUID
    track_id: UUID
    quality_score: int
    zone: str
    is_best: bool = False
