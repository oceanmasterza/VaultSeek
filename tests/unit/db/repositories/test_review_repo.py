"""Unit tests for musicvault.db.repositories.review_repo.ReviewRepository."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Engine

from musicvault.db.repositories.review_repo import ReviewRepository
from musicvault.db.uuid_utils import generate_uuid7
from musicvault.models.entities.review_item import ReviewItem, ReviewStatus, ReviewType

_NOW = datetime(2026, 7, 15, tzinfo=UTC)


def _make_review_item(library_id: UUID, **overrides: object) -> ReviewItem:
    defaults: dict[str, object] = {
        "id": generate_uuid7(),
        "library_id": library_id,
        "review_type": ReviewType.UNKNOWN_ARTIST,
        "status": ReviewStatus.PENDING,
        "title": "Unknown artist",
        "created_at": _NOW,
    }
    defaults.update(overrides)
    return ReviewItem(**defaults)  # type: ignore[arg-type]


def test_create_and_get_round_trips_every_field(
    engine: Engine, library_id: UUID, track_id: UUID
) -> None:
    repo = ReviewRepository(engine)
    item = _make_review_item(
        library_id,
        track_id=track_id,
        description="Could not identify artist from tags",
        confidence=0.42,
        payload={"candidates": ["Artist A", "Artist B"]},
    )

    repo.create(item)
    loaded = repo.get(item.id)

    assert loaded == item


def test_get_returns_none_for_missing_review_item(engine: Engine) -> None:
    repo = ReviewRepository(engine)

    assert repo.get(generate_uuid7()) is None


def test_list_by_status_filters_correctly(engine: Engine, library_id: UUID) -> None:
    repo = ReviewRepository(engine)
    pending = _make_review_item(library_id, status=ReviewStatus.PENDING)
    approved = _make_review_item(library_id, status=ReviewStatus.APPROVED)
    repo.create(pending)
    repo.create(approved)

    results = repo.list_by_status(ReviewStatus.PENDING)

    assert {item.id for item in results} == {pending.id}


def test_list_by_status_filters_by_library_when_given(engine: Engine, library_id: UUID) -> None:
    repo = ReviewRepository(engine)
    item = _make_review_item(library_id, status=ReviewStatus.PENDING)
    repo.create(item)

    same_library_results = repo.list_by_status(ReviewStatus.PENDING, library_id=library_id)
    other_library_results = repo.list_by_status(ReviewStatus.PENDING, library_id=generate_uuid7())

    assert {i.id for i in same_library_results} == {item.id}
    assert other_library_results == []


def test_resolve_sets_status_resolved_by_and_resolved_at(engine: Engine, library_id: UUID) -> None:
    repo = ReviewRepository(engine)
    item = _make_review_item(library_id)
    repo.create(item)

    repo.resolve(item.id, ReviewStatus.APPROVED, resolved_by="user", resolved_at=_NOW)

    loaded = repo.get(item.id)
    assert loaded is not None
    assert loaded.status is ReviewStatus.APPROVED
    assert loaded.resolved_by == "user"
    assert loaded.resolved_at == _NOW
