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

    def resolve(
        self,
        review_id: UUID,
        status: ReviewStatus,
        *,
        resolved_by: str,
        resolved_at: datetime,
    ) -> None:
        """Mark a review item as approved/rejected/deferred, recording who and when.

        ``resolved_at`` is a required parameter rather than an internal
        ``datetime.now()`` call so this method stays deterministic and
        testable — the caller (a future service layer, or a test) decides
        what "now" means.
        """
        with self._engine.begin() as conn:
            conn.execute(
                update(review_items)
                .where(review_items.c.id == uuid_to_blob(review_id))
                .values(
                    status=status.value,
                    resolved_by=resolved_by,
                    resolved_at=resolved_at.isoformat(),
                )
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
