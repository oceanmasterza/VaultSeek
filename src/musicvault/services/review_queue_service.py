"""ReviewQueueService — human approval gate for uncertain metadata.

Auto-created by :class:`~musicvault.workers.io.metadata_worker.MetadataWorker`
when arbitration sets ``needs_review``. Approve / reject / defer / edit
are called by the Review UI (Phase 14) or tests today.

Approve clears ``tracks.needs_review`` but does **not** move zones —
staging → library is Phase 10 (:class:`~musicvault.models.services.organize_engine.OrganizeEngine`).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from musicvault.core.event_bus import EventBus
from musicvault.core.exceptions import ReviewError
from musicvault.db.repositories.review_repo import ReviewRepository
from musicvault.db.repositories.track_repo import TrackRepository
from musicvault.db.uuid_utils import generate_uuid7
from musicvault.models.entities.review_item import ReviewItem, ReviewStatus, ReviewType
from musicvault.models.interfaces.metadata import ArbitrationResult
from musicvault.services.dto.review_dto import ReviewItemCreate
from musicvault.services.events import ReviewItemAddedEvent

_PROVIDER_CONFLICT_GAP = 0.10
_EDITABLE_TRACK_FIELDS = frozenset(
    {
        "title",
        "year",
        "genre",
        "composer",
        "track_number",
        "disc_number",
        "mb_recording_id",
    }
)
_TITLE_BY_TYPE = {
    ReviewType.UNKNOWN_ARTIST: "Unknown or low-confidence artist",
    ReviewType.UNKNOWN_ALBUM: "Unknown or low-confidence album",
    ReviewType.METADATA_CONFLICT: "Providers disagree on metadata",
}


class ReviewQueueService:
    def __init__(
        self,
        review_repository: ReviewRepository,
        track_repository: TrackRepository,
        event_bus: EventBus,
        *,
        confidence_threshold: float = 0.90,
    ) -> None:
        self._reviews = review_repository
        self._tracks = track_repository
        self._events = event_bus
        self._threshold = confidence_threshold

    def create_item(self, item: ReviewItemCreate, *, now: datetime | None = None) -> UUID:
        """Insert a pending review item, or refresh an existing pending one
        for the same ``(track_id, review_type)`` (idempotent re-identify)."""
        created_at = _resolve_now(now)
        if item.track_id is not None:
            existing = self._reviews.find_pending(
                track_id=item.track_id, review_type=item.review_type
            )
            if existing is not None:
                self._reviews.update_pending_content(
                    existing.id,
                    title=item.title,
                    description=item.description,
                    confidence=item.confidence,
                    payload=item.payload,
                )
                self._events.publish(
                    ReviewItemAddedEvent(
                        review_id=existing.id,
                        library_id=item.library_id,
                        review_type=item.review_type,
                        track_id=item.track_id,
                    )
                )
                return existing.id

        review_id = generate_uuid7()
        self._reviews.create(
            ReviewItem(
                id=review_id,
                library_id=item.library_id,
                review_type=item.review_type,
                status=ReviewStatus.PENDING,
                title=item.title,
                created_at=created_at,
                track_id=item.track_id,
                album_id=item.album_id,
                description=item.description,
                confidence=item.confidence,
                payload=item.payload,
            )
        )
        self._events.publish(
            ReviewItemAddedEvent(
                review_id=review_id,
                library_id=item.library_id,
                review_type=item.review_type,
                track_id=item.track_id,
            )
        )
        return review_id

    def create_from_arbitration(
        self,
        *,
        library_id: UUID,
        track_id: UUID,
        result: ArbitrationResult,
        now: datetime | None = None,
    ) -> UUID:
        """Classify and enqueue a review item from an :class:`ArbitrationResult`."""
        review_type = classify_review_type(result, self._threshold)
        return self.create_item(
            ReviewItemCreate(
                library_id=library_id,
                review_type=review_type,
                title=_TITLE_BY_TYPE.get(review_type, "Needs review"),
                track_id=track_id,
                description=_describe(result, review_type),
                confidence=result.overall_confidence,
                payload=_payload_from_result(result),
            ),
            now=now,
        )

    def get_pending(self, library_id: UUID) -> Sequence[ReviewItem]:
        """Return pending items for a library (deferred items are excluded)."""
        return self._reviews.list_by_status(ReviewStatus.PENDING, library_id=library_id)

    def get_by_type(self, library_id: UUID, review_type: ReviewType) -> Sequence[ReviewItem]:
        return self._reviews.list_by_type(review_type, library_id=library_id)

    def approve(
        self, item_id: UUID, *, resolved_by: str = "user", now: datetime | None = None
    ) -> None:
        """Accept the arbitrated metadata and clear ``needs_review``.

        Does not change library zones (Phase 10).
        """
        item = self._require_pending(item_id)
        resolved_at = _resolve_now(now)
        self._reviews.resolve(
            item_id, ReviewStatus.APPROVED, resolved_by=resolved_by, resolved_at=resolved_at
        )
        self._clear_needs_review(item.track_id, resolved_at)

    def reject(
        self,
        item_id: UUID,
        reason: str | None = None,
        *,
        resolved_by: str = "user",
        now: datetime | None = None,
    ) -> None:
        """Reject the item. Leaves ``tracks.needs_review`` set so it stays visible."""
        item = self._require_pending(item_id)
        description = item.description
        if reason:
            description = f"{description}\nReject reason: {reason}" if description else reason
        self._reviews.resolve(
            item_id,
            ReviewStatus.REJECTED,
            resolved_by=resolved_by,
            resolved_at=_resolve_now(now),
            description=description,
        )

    def defer(
        self, item_id: UUID, *, resolved_by: str = "user", now: datetime | None = None
    ) -> None:
        """Park the item outside the pending list. Leaves ``needs_review`` set."""
        self._require_pending(item_id)
        self._reviews.resolve(
            item_id,
            ReviewStatus.DEFERRED,
            resolved_by=resolved_by,
            resolved_at=_resolve_now(now),
        )

    def approve_with_edits(
        self,
        item_id: UUID,
        edits: dict[str, Any],
        *,
        resolved_by: str = "user",
        now: datetime | None = None,
    ) -> None:
        """Apply user field edits to the track, then approve."""
        unknown = set(edits) - _EDITABLE_TRACK_FIELDS
        if unknown:
            raise ReviewError(f"Unsupported review edits: {sorted(unknown)}")
        item = self._require_pending(item_id)
        if item.track_id is None:
            raise ReviewError(f"Review item {item_id} has no track to edit")
        track = self._tracks.get_by_id(item.track_id)
        if track is None:
            raise ReviewError(f"Track {item.track_id} not found for review {item_id}")

        resolved_at = _resolve_now(now)
        updates: dict[str, object] = {
            "needs_review": False,
            "updated_at": resolved_at,
        }
        for key, value in edits.items():
            updates[key] = value
        self._tracks.upsert(replace(track, **updates))  # type: ignore[arg-type]
        self._reviews.resolve(
            item_id, ReviewStatus.APPROVED, resolved_by=resolved_by, resolved_at=resolved_at
        )

    def _require_pending(self, item_id: UUID) -> ReviewItem:
        item = self._reviews.get(item_id)
        if item is None:
            raise ReviewError(f"Review item {item_id} not found")
        if item.status is not ReviewStatus.PENDING:
            raise ReviewError(f"Review item {item_id} is {item.status.value}, expected pending")
        return item

    def _clear_needs_review(self, track_id: UUID | None, now: datetime) -> None:
        if track_id is None:
            return
        track = self._tracks.get_by_id(track_id)
        if track is None:
            return
        self._tracks.upsert(replace(track, needs_review=False, updated_at=now))


def classify_review_type(result: ArbitrationResult, threshold: float) -> ReviewType:
    """Pick a :class:`ReviewType` from arbitration fields.

    Priority: weak/missing artist → weak/missing album → near-tie provider
    conflict → catch-all ``unknown_artist``.
    """
    artist = result.fields.get("artist")
    if artist is None or artist.confidence < threshold:
        return ReviewType.UNKNOWN_ARTIST
    album = result.fields.get("album")
    if album is None or album.confidence < threshold:
        return ReviewType.UNKNOWN_ALBUM
    if _has_provider_conflict(result, gap=_PROVIDER_CONFLICT_GAP):
        return ReviewType.METADATA_CONFLICT
    return ReviewType.UNKNOWN_ARTIST


def _has_provider_conflict(result: ArbitrationResult, *, gap: float) -> bool:
    by_field: dict[str, list[tuple[object, float]]] = defaultdict(list)
    for provider in result.provider_results:
        for field in provider.fields:
            if field.value is None or field.value == "":
                continue
            by_field[field.field].append((field.value, field.confidence))
    for candidates in by_field.values():
        if len(candidates) < 2:
            continue
        ranked = sorted(candidates, key=lambda item: item[1], reverse=True)
        top_value, top_confidence = ranked[0]
        for value, confidence in ranked[1:]:
            if top_confidence - confidence <= gap and value != top_value:
                return True
    return False


def _describe(result: ArbitrationResult, review_type: ReviewType) -> str:
    overall = f"Overall confidence {result.overall_confidence:.2f}"
    if review_type is ReviewType.METADATA_CONFLICT:
        return f"{overall}; providers disagree on one or more fields"
    if review_type is ReviewType.UNKNOWN_ALBUM:
        album = result.fields.get("album")
        if album is None:
            return f"{overall}; album missing"
        return f"{overall}; album confidence {album.confidence:.2f}"
    artist = result.fields.get("artist")
    if artist is None:
        return f"{overall}; artist missing"
    return f"{overall}; artist confidence {artist.confidence:.2f}"


def _payload_from_result(result: ArbitrationResult) -> dict[str, Any]:
    return {
        "overall_confidence": result.overall_confidence,
        "fields": {
            name: {
                "value": field.value,
                "confidence": field.confidence,
                "source": field.source,
            }
            for name, field in result.fields.items()
        },
    }


def _resolve_now(now: datetime | None) -> datetime:
    return now if now is not None else datetime.now(UTC)
