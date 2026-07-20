"""ReviewItem entity — a single entry in the human review queue.

Mirrors the `review_items` table (see
docs/architecture/03-database-schema.md, "Review Queue"). Pulled forward
from Phase 3 for the same reason as :class:`~vaultseek.models.entities.job.Job`
— it is the return type :class:`~vaultseek.db.repositories.review_repo.ReviewRepository`
needs now. The composite confidence scoring that actually populates this
queue (see docs/architecture/12-pipeline-engine-v3.md) is still Phase 8.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID


class ReviewType(StrEnum):
    UNKNOWN_ARTIST = "unknown_artist"
    UNKNOWN_ALBUM = "unknown_album"
    METADATA_CONFLICT = "metadata_conflict"
    POSSIBLE_DUPLICATE = "possible_duplicate"
    ARTWORK_MISSING = "artwork_missing"
    ARTWORK_LOW_RES = "artwork_low_res"
    LOW_QUALITY = "low_quality"
    RULE_ACTION = "rule_action"


class ReviewStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    DEFERRED = "deferred"


@dataclass(frozen=True, slots=True)
class ReviewItem:
    """A single human-review-queue entry, persisted in `review_items`."""

    id: UUID
    library_id: UUID
    review_type: ReviewType
    status: ReviewStatus
    title: str
    created_at: datetime
    track_id: UUID | None = None
    album_id: UUID | None = None
    duplicate_group_id: UUID | None = None
    description: str | None = None
    confidence: float | None = None
    payload: dict[str, Any] | None = None
    resolved_at: datetime | None = None
    resolved_by: str | None = None
