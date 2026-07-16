"""DTOs for the human review queue (Phase 7)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from musicvault.models.entities.review_item import ReviewType


@dataclass(frozen=True, slots=True)
class ReviewItemCreate:
    """Input for ReviewQueueService.create_item."""

    library_id: UUID
    review_type: ReviewType
    title: str
    track_id: UUID | None = None
    album_id: UUID | None = None
    description: str | None = None
    confidence: float | None = None
    payload: dict[str, Any] = field(default_factory=dict)
