"""ReviewRepository — persistence for the `review_items` table."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Engine, Row, insert, select, update

from musicvault.db.tables import review_items
from musicvault.db.uuid_utils import blob_to_uuid, uuid_to_blob
from musicvault.models.entities.review_item import ReviewItem, ReviewStatus, ReviewType


class ReviewRepository:
    """Reads and writes `ReviewItem` entities against `review_items`."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def create(self, item: ReviewItem) -> None:
        with self._engine.begin() as conn:
            conn.execute(insert(review_items).values(**_to_row(item)))

    def get(self, review_id: UUID) -> ReviewItem | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                select(review_items).where(review_items.c.id == uuid_to_blob(review_id))
            ).first()
        return _from_row(row) if row is not None else None

    def list_by_status(
        self, status: ReviewStatus, *, library_id: UUID | None = None
    ) -> list[ReviewItem]:
        statement = select(review_items).where(review_items.c.status == status.value)
        if library_id is not None:
            statement = statement.where(review_items.c.library_id == uuid_to_blob(library_id))

        with self._engine.connect() as conn:
            rows = conn.execute(statement).all()
        return [_from_row(row) for row in rows]

    def list_by_type(
        self,
        review_type: ReviewType,
        *,
        library_id: UUID,
        status: ReviewStatus = ReviewStatus.PENDING,
    ) -> list[ReviewItem]:
        statement = (
            select(review_items)
            .where(review_items.c.library_id == uuid_to_blob(library_id))
            .where(review_items.c.review_type == review_type.value)
            .where(review_items.c.status == status.value)
        )
        with self._engine.connect() as conn:
            rows = conn.execute(statement).all()
        return [_from_row(row) for row in rows]

    def find_pending(self, *, track_id: UUID, review_type: ReviewType) -> ReviewItem | None:
        """Return the open pending item for ``(track_id, review_type)``, if any."""
        statement = (
            select(review_items)
            .where(review_items.c.track_id == uuid_to_blob(track_id))
            .where(review_items.c.review_type == review_type.value)
            .where(review_items.c.status == ReviewStatus.PENDING.value)
        )
        with self._engine.connect() as conn:
            row = conn.execute(statement).first()
        return _from_row(row) if row is not None else None

    def list_pending_for_track(self, track_id: UUID) -> list[ReviewItem]:
        """All pending items attached to this track (any review type)."""
        statement = (
            select(review_items)
            .where(review_items.c.track_id == uuid_to_blob(track_id))
            .where(review_items.c.status == ReviewStatus.PENDING.value)
        )
        with self._engine.connect() as conn:
            rows = conn.execute(statement).all()
        return [_from_row(row) for row in rows]

    def update_pending_content(
        self,
        review_id: UUID,
        *,
        title: str,
        description: str | None,
        confidence: float | None,
        payload: dict[str, Any] | None,
    ) -> None:
        """Refresh display fields on an existing pending review item."""
        with self._engine.begin() as conn:
            conn.execute(
                update(review_items)
                .where(review_items.c.id == uuid_to_blob(review_id))
                .values(
                    title=title,
                    description=description,
                    confidence=confidence,
                    payload=json.dumps(payload) if payload is not None else None,
                )
            )

    def resolve(
        self,
        review_id: UUID,
        status: ReviewStatus,
        *,
        resolved_by: str,
        resolved_at: datetime,
        description: str | None = None,
    ) -> None:
        """Mark a review item as approved/rejected/deferred, recording who and when.

        ``resolved_at`` is a required parameter rather than an internal
        ``datetime.now()`` call so this method stays deterministic and
        testable — the caller (service layer or test) decides what "now"
        means. Optional ``description`` updates the stored text (used when
        recording a reject reason).
        """
        values: dict[str, object] = {
            "status": status.value,
            "resolved_by": resolved_by,
            "resolved_at": resolved_at.isoformat(),
        }
        if description is not None:
            values["description"] = description
        with self._engine.begin() as conn:
            conn.execute(
                update(review_items)
                .where(review_items.c.id == uuid_to_blob(review_id))
                .values(**values)
            )


def _to_row(item: ReviewItem) -> dict[str, object]:
    return {
        "id": uuid_to_blob(item.id),
        "library_id": uuid_to_blob(item.library_id),
        "track_id": uuid_to_blob(item.track_id) if item.track_id else None,
        "album_id": uuid_to_blob(item.album_id) if item.album_id else None,
        "duplicate_group_id": (
            uuid_to_blob(item.duplicate_group_id) if item.duplicate_group_id else None
        ),
        "review_type": item.review_type.value,
        "status": item.status.value,
        "title": item.title,
        "description": item.description,
        "confidence": item.confidence,
        "payload": json.dumps(item.payload) if item.payload is not None else None,
        "created_at": item.created_at.isoformat(),
        "resolved_at": item.resolved_at.isoformat() if item.resolved_at else None,
        "resolved_by": item.resolved_by,
    }


def _from_row(row: Row[Any]) -> ReviewItem:
    return ReviewItem(
        id=blob_to_uuid(row.id),
        library_id=blob_to_uuid(row.library_id),
        review_type=ReviewType(row.review_type),
        status=ReviewStatus(row.status),
        title=row.title,
        created_at=datetime.fromisoformat(row.created_at),
        track_id=blob_to_uuid(row.track_id) if row.track_id else None,
        album_id=blob_to_uuid(row.album_id) if row.album_id else None,
        duplicate_group_id=(
            blob_to_uuid(row.duplicate_group_id) if row.duplicate_group_id else None
        ),
        description=row.description,
        confidence=row.confidence,
        payload=json.loads(row.payload) if row.payload is not None else None,
        resolved_at=datetime.fromisoformat(row.resolved_at) if row.resolved_at else None,
        resolved_by=row.resolved_by,
    )
