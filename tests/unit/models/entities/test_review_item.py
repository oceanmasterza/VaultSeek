"""Unit tests for vaultseek.models.entities.review_item."""

from __future__ import annotations

from datetime import UTC, datetime

from vaultseek.db.uuid_utils import generate_uuid7
from vaultseek.models.entities.review_item import ReviewItem, ReviewStatus, ReviewType

_NOW = datetime(2026, 7, 15, tzinfo=UTC)


def _make_review_item(**overrides: object) -> ReviewItem:
    defaults: dict[str, object] = {
        "id": generate_uuid7(),
        "library_id": generate_uuid7(),
        "review_type": ReviewType.UNKNOWN_ARTIST,
        "status": ReviewStatus.PENDING,
        "title": "Unknown artist for 'Untitled Track'",
        "created_at": _NOW,
    }
    defaults.update(overrides)
    return ReviewItem(**defaults)  # type: ignore[arg-type]


def test_review_item_applies_documented_defaults() -> None:
    item = _make_review_item()

    assert item.track_id is None
    assert item.album_id is None
    assert item.duplicate_group_id is None
    assert item.description is None
    assert item.confidence is None
    assert item.payload is None
    assert item.resolved_at is None
    assert item.resolved_by is None


def test_review_type_covers_every_documented_trigger() -> None:
    expected = {
        "unknown_artist",
        "unknown_album",
        "metadata_conflict",
        "possible_duplicate",
        "artwork_missing",
        "artwork_low_res",
        "low_quality",
        "rule_action",
        "acquisition_failed",
        "acquisition_no_results",
        "acquisition_needs_choice",
    }

    assert {member.value for member in ReviewType} == expected


def test_review_status_covers_every_documented_state() -> None:
    expected = {"pending", "approved", "rejected", "deferred"}

    assert {member.value for member in ReviewStatus} == expected


def test_review_item_can_be_resolved_with_full_context() -> None:
    item = _make_review_item(
        status=ReviewStatus.APPROVED,
        track_id=generate_uuid7(),
        confidence=0.42,
        resolved_at=_NOW,
        resolved_by="user",
    )

    assert item.status is ReviewStatus.APPROVED
    assert item.resolved_by == "user"
