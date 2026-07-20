"""Domain events published by application services."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from vaultseek.core.event_bus import DomainEvent
from vaultseek.models.entities.review_item import ReviewType


@dataclass(frozen=True, kw_only=True)
class ReviewItemAddedEvent(DomainEvent):
    """A new (or refreshed) pending review item was written to the queue.

    The Qt bridge (Phase 14) will subscribe to this to refresh the Review
    page badge; until then it is published for observability and tests.
    """

    review_id: UUID
    library_id: UUID
    review_type: ReviewType
    track_id: UUID | None = None


@dataclass(frozen=True, kw_only=True)
class RulesMatchedEvent(DomainEvent):
    """One or more automation rules matched a track during evaluation."""

    library_id: UUID
    track_id: UUID
    rule_ids: tuple[UUID, ...]
