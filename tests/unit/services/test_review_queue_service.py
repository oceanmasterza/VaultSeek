"""Unit tests for ReviewQueueService."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from musicvault.core.event_bus import EventBus
from musicvault.core.exceptions import ReviewError
from musicvault.db.repositories.duplicate_repo import DuplicateRepository
from musicvault.db.repositories.job_repo import JobRepository
from musicvault.db.repositories.review_repo import ReviewRepository
from musicvault.db.repositories.track_repo import TrackRepository
from musicvault.models.entities.duplicate_group import (
    DuplicateGroup,
    DuplicateMember,
    GroupResolution,
    GroupStatus,
    MatchType,
)
from musicvault.models.entities.job import JobStatus, JobType
from musicvault.models.entities.review_item import ReviewStatus, ReviewType
from musicvault.models.entities.track import LibraryZone, Track
from musicvault.models.interfaces.metadata import (
    ArbitrationResult,
    ProviderFieldResult,
    ProviderResult,
)
from musicvault.models.value_objects.field_confidence import FieldConfidence
from musicvault.services.dto.review_dto import ReviewItemCreate
from musicvault.services.events import ReviewItemAddedEvent
from musicvault.services.job_queue_service import JobQueueService
from musicvault.services.review_queue_service import ReviewQueueService, classify_review_type

_NOW = datetime(2026, 7, 16, tzinfo=UTC)


def _make_track(library_id: UUID, track_id: UUID, **overrides: object) -> Track:
    defaults: dict[str, object] = {
        "id": track_id,
        "library_id": library_id,
        "zone": LibraryZone.INCOMING,
        "file_path": "C:/incoming/track.flac",
        "file_name": "track.flac",
        "file_size": 1024,
        "file_modified": _NOW,
        "created_at": _NOW,
        "updated_at": _NOW,
        "needs_review": True,
        "overall_confidence": 0.55,
    }
    defaults.update(overrides)
    return Track(**defaults)  # type: ignore[arg-type]


def test_create_item_persists_and_publishes_event(
    review_queue: ReviewQueueService,
    event_bus: EventBus,
    library_id: UUID,
    track_id: UUID,
) -> None:
    received: list[ReviewItemAddedEvent] = []
    event_bus.subscribe(ReviewItemAddedEvent, received.append)

    review_id = review_queue.create_item(
        ReviewItemCreate(
            library_id=library_id,
            review_type=ReviewType.UNKNOWN_ARTIST,
            title="Unknown artist",
            track_id=track_id,
            confidence=0.4,
            description="artist missing",
            payload={"overall_confidence": 0.4},
        ),
        now=_NOW,
    )

    pending = review_queue.get_pending(library_id)
    assert len(pending) == 1
    assert pending[0].id == review_id
    assert pending[0].review_type is ReviewType.UNKNOWN_ARTIST
    assert len(received) == 1
    assert received[0].review_id == review_id
    assert received[0].track_id == track_id


def test_create_item_upserts_pending_for_same_track_and_type(
    review_queue: ReviewQueueService, library_id: UUID, track_id: UUID
) -> None:
    first = review_queue.create_item(
        ReviewItemCreate(
            library_id=library_id,
            review_type=ReviewType.UNKNOWN_ARTIST,
            title="First",
            track_id=track_id,
            confidence=0.3,
        ),
        now=_NOW,
    )
    second = review_queue.create_item(
        ReviewItemCreate(
            library_id=library_id,
            review_type=ReviewType.UNKNOWN_ARTIST,
            title="Updated",
            track_id=track_id,
            confidence=0.5,
            description="refreshed",
        ),
        now=_NOW,
    )

    assert first == second
    pending = review_queue.get_pending(library_id)
    assert len(pending) == 1
    assert pending[0].title == "Updated"
    assert pending[0].confidence == 0.5
    assert pending[0].description == "refreshed"


def test_approve_clears_needs_review(
    review_queue: ReviewQueueService,
    track_repo: TrackRepository,
    library_id: UUID,
    track_id: UUID,
) -> None:
    track_repo.upsert(_make_track(library_id, track_id))
    review_id = review_queue.create_item(
        ReviewItemCreate(
            library_id=library_id,
            review_type=ReviewType.UNKNOWN_ARTIST,
            title="Review me",
            track_id=track_id,
        ),
        now=_NOW,
    )

    review_queue.approve(review_id, now=_NOW)

    pending = review_queue.get_pending(library_id)
    assert pending == []
    updated = track_repo.get_by_id(track_id)
    assert updated is not None
    assert updated.needs_review is False
    assert updated.zone is LibraryZone.INCOMING


def test_reject_with_reason_leaves_needs_review(
    review_queue: ReviewQueueService,
    track_repo: TrackRepository,
    review_repo: ReviewRepository,
    library_id: UUID,
    track_id: UUID,
) -> None:
    track_repo.upsert(_make_track(library_id, track_id))
    review_id = review_queue.create_item(
        ReviewItemCreate(
            library_id=library_id,
            review_type=ReviewType.UNKNOWN_ALBUM,
            title="Album?",
            track_id=track_id,
            description="album missing",
        ),
        now=_NOW,
    )

    review_queue.reject(review_id, reason="Wrong match", now=_NOW)

    assert review_queue.get_pending(library_id) == []
    loaded = review_repo.get(review_id)
    assert loaded is not None
    assert loaded.status is ReviewStatus.REJECTED
    assert loaded.description is not None
    assert "Wrong match" in loaded.description
    track = track_repo.get_by_id(track_id)
    assert track is not None
    assert track.needs_review is True


def test_defer_excludes_from_pending(
    review_queue: ReviewQueueService, library_id: UUID, track_id: UUID
) -> None:
    review_id = review_queue.create_item(
        ReviewItemCreate(
            library_id=library_id,
            review_type=ReviewType.METADATA_CONFLICT,
            title="Conflict",
            track_id=track_id,
        ),
        now=_NOW,
    )

    review_queue.defer(review_id, now=_NOW)

    assert review_queue.get_pending(library_id) == []
    by_type = review_queue.get_by_type(library_id, ReviewType.METADATA_CONFLICT)
    assert by_type == []


def test_approve_with_edits_updates_track_fields(
    review_queue: ReviewQueueService,
    track_repo: TrackRepository,
    library_id: UUID,
    track_id: UUID,
) -> None:
    track_repo.upsert(_make_track(library_id, track_id, title="Old"))
    review_id = review_queue.create_item(
        ReviewItemCreate(
            library_id=library_id,
            review_type=ReviewType.UNKNOWN_ARTIST,
            title="Edit me",
            track_id=track_id,
        ),
        now=_NOW,
    )

    review_queue.approve_with_edits(review_id, {"title": "Correct Title", "year": 1999}, now=_NOW)

    updated = track_repo.get_by_id(track_id)
    assert updated is not None
    assert updated.title == "Correct Title"
    assert updated.year == 1999
    assert updated.needs_review is False
    assert review_queue.get_pending(library_id) == []


def test_approve_with_edits_rejects_unknown_fields(
    review_queue: ReviewQueueService, library_id: UUID, track_id: UUID
) -> None:
    review_id = review_queue.create_item(
        ReviewItemCreate(
            library_id=library_id,
            review_type=ReviewType.UNKNOWN_ARTIST,
            title="Bad edit",
            track_id=track_id,
        ),
        now=_NOW,
    )

    with pytest.raises(ReviewError, match="Unsupported"):
        review_queue.approve_with_edits(review_id, {"file_path": "evil"}, now=_NOW)


def test_approve_non_pending_raises(
    review_queue: ReviewQueueService, library_id: UUID, track_id: UUID
) -> None:
    review_id = review_queue.create_item(
        ReviewItemCreate(
            library_id=library_id,
            review_type=ReviewType.UNKNOWN_ARTIST,
            title="Once",
            track_id=track_id,
        ),
        now=_NOW,
    )
    review_queue.defer(review_id, now=_NOW)

    with pytest.raises(ReviewError, match="deferred"):
        review_queue.approve(review_id, now=_NOW)


def test_create_from_arbitration_classifies_unknown_artist(
    review_queue: ReviewQueueService, library_id: UUID, track_id: UUID
) -> None:
    result = ArbitrationResult(
        track_id=track_id,
        fields={
            "title": FieldConfidence("title", "Song", 0.95, "local_tags"),
        },
        overall_confidence=0.50,
        needs_review=True,
    )

    review_id = review_queue.create_from_arbitration(
        library_id=library_id, track_id=track_id, result=result, now=_NOW
    )

    pending = review_queue.get_pending(library_id)
    assert len(pending) == 1
    assert pending[0].id == review_id
    assert pending[0].review_type is ReviewType.UNKNOWN_ARTIST


def test_classify_review_type_prefers_album_then_conflict() -> None:
    track_id = UUID("01800000-0000-7000-8000-000000000001")
    weak_album = ArbitrationResult(
        track_id=track_id,
        fields={
            "artist": FieldConfidence("artist", "A", 0.95, "musicbrainz"),
            "album": FieldConfidence("album", "?", 0.40, "filename_parser"),
        },
        overall_confidence=0.40,
        needs_review=True,
    )
    assert classify_review_type(weak_album, 0.90) is ReviewType.UNKNOWN_ALBUM

    conflict = ArbitrationResult(
        track_id=track_id,
        fields={
            "artist": FieldConfidence("artist", "A", 0.95, "musicbrainz"),
            "album": FieldConfidence("album", "Album", 0.92, "musicbrainz"),
            "title": FieldConfidence("title", "T1", 0.91, "musicbrainz"),
        },
        overall_confidence=0.85,
        needs_review=True,
        provider_results=[
            ProviderResult(
                provider_id="musicbrainz",
                fields=[ProviderFieldResult("title", "T1", 0.91)],
                overall_confidence=0.91,
                lookup_method="tags",
            ),
            ProviderResult(
                provider_id="local_tags",
                fields=[ProviderFieldResult("title", "T2", 0.90)],
                overall_confidence=0.90,
                lookup_method="tags",
            ),
        ],
    )
    assert classify_review_type(conflict, 0.90) is ReviewType.METADATA_CONFLICT


# ---------------------------------------------------------------------------
# Phase 10: approval triggers zone moves (wired review queue)
# ---------------------------------------------------------------------------


@pytest.fixture
def wired_review_queue(
    review_repo: ReviewRepository,
    track_repo: TrackRepository,
    event_bus: EventBus,
    job_queue: JobQueueService,
    duplicate_repo: DuplicateRepository,
) -> ReviewQueueService:
    return ReviewQueueService(
        review_repo,
        track_repo,
        event_bus,
        confidence_threshold=0.90,
        job_queue=job_queue,
        duplicate_repository=duplicate_repo,
    )


def _pending_organize_jobs(job_repo: JobRepository) -> list[dict[str, object]]:
    return [
        job.payload
        for job in job_repo.list_by_status(JobStatus.PENDING)
        if job.job_type is JobType.ORGANIZE_FILE
    ]


def test_approve_rule_action_executes_parked_move_from_actions_list(
    wired_review_queue: ReviewQueueService,
    track_repo: TrackRepository,
    job_repo: JobRepository,
    library_id: UUID,
    track_id: UUID,
) -> None:
    """The shipped archive-MP3 rule parks its actions list behind approval;
    approving must enqueue the archive move."""
    track_repo.upsert(_make_track(library_id, track_id, zone=LibraryZone.STAGING))
    review_id = wired_review_queue.create_item(
        ReviewItemCreate(
            library_id=library_id,
            review_type=ReviewType.RULE_ACTION,
            title="Rule requires approval: Archive MP3 when FLAC exists",
            track_id=track_id,
            payload={
                "rule_id": "irrelevant",
                "rule_name": "Archive MP3 when FLAC exists",
                "actions": [{"action_type": "move_to_zone", "parameters": {"zone": "archive"}}],
            },
        ),
        now=_NOW,
    )

    wired_review_queue.approve(review_id, now=_NOW)

    assert _pending_organize_jobs(job_repo) == [
        {"track_id": str(track_id), "target_zone": "archive"}
    ]


def test_approve_rule_action_executes_parked_move_from_flat_payload(
    wired_review_queue: ReviewQueueService,
    track_repo: TrackRepository,
    job_repo: JobRepository,
    library_id: UUID,
    track_id: UUID,
) -> None:
    track_repo.upsert(_make_track(library_id, track_id, zone=LibraryZone.INCOMING))
    review_id = wired_review_queue.create_item(
        ReviewItemCreate(
            library_id=library_id,
            review_type=ReviewType.RULE_ACTION,
            title="Rule wants zone 'staging'",
            track_id=track_id,
            payload={"rule_id": "x", "action_type": "move_to_zone", "zone": "staging"},
        ),
        now=_NOW,
    )

    wired_review_queue.approve(review_id, now=_NOW)

    assert _pending_organize_jobs(job_repo) == [
        {"track_id": str(track_id), "target_zone": "staging"}
    ]


def test_approve_rule_action_skips_illegal_parked_move(
    wired_review_queue: ReviewQueueService,
    track_repo: TrackRepository,
    job_repo: JobRepository,
    library_id: UUID,
    track_id: UUID,
) -> None:
    track_repo.upsert(_make_track(library_id, track_id, zone=LibraryZone.INCOMING))
    review_id = wired_review_queue.create_item(
        ReviewItemCreate(
            library_id=library_id,
            review_type=ReviewType.RULE_ACTION,
            title="Rule wants zone 'library'",
            track_id=track_id,
            payload={"rule_id": "x", "action_type": "move_to_zone", "zone": "library"},
        ),
        now=_NOW,
    )

    wired_review_queue.approve(review_id, now=_NOW)

    assert _pending_organize_jobs(job_repo) == []


def test_approve_metadata_item_promotes_staging_track_to_library(
    wired_review_queue: ReviewQueueService,
    track_repo: TrackRepository,
    job_repo: JobRepository,
    library_id: UUID,
    track_id: UUID,
) -> None:
    track_repo.upsert(_make_track(library_id, track_id, zone=LibraryZone.STAGING))
    review_id = wired_review_queue.create_item(
        ReviewItemCreate(
            library_id=library_id,
            review_type=ReviewType.UNKNOWN_ARTIST,
            title="Who is this",
            track_id=track_id,
        ),
        now=_NOW,
    )

    wired_review_queue.approve(review_id, now=_NOW)

    assert _pending_organize_jobs(job_repo) == [
        {"track_id": str(track_id), "target_zone": "library"}
    ]


def test_approve_metadata_item_leaves_incoming_track_to_the_pipeline(
    wired_review_queue: ReviewQueueService,
    track_repo: TrackRepository,
    job_repo: JobRepository,
    library_id: UUID,
    track_id: UUID,
) -> None:
    track_repo.upsert(_make_track(library_id, track_id, zone=LibraryZone.INCOMING))
    review_id = wired_review_queue.create_item(
        ReviewItemCreate(
            library_id=library_id,
            review_type=ReviewType.UNKNOWN_ARTIST,
            title="Who is this",
            track_id=track_id,
        ),
        now=_NOW,
    )

    wired_review_queue.approve(review_id, now=_NOW)

    assert _pending_organize_jobs(job_repo) == []


def test_approve_with_edits_also_runs_post_approve_moves(
    wired_review_queue: ReviewQueueService,
    track_repo: TrackRepository,
    job_repo: JobRepository,
    library_id: UUID,
    track_id: UUID,
) -> None:
    track_repo.upsert(_make_track(library_id, track_id, zone=LibraryZone.STAGING))
    review_id = wired_review_queue.create_item(
        ReviewItemCreate(
            library_id=library_id,
            review_type=ReviewType.UNKNOWN_ALBUM,
            title="Album?",
            track_id=track_id,
        ),
        now=_NOW,
    )

    wired_review_queue.approve_with_edits(review_id, {"title": "Fixed"}, now=_NOW)

    assert _pending_organize_jobs(job_repo) == [
        {"track_id": str(track_id), "target_zone": "library"}
    ]


def test_approve_possible_duplicate_resolves_group_and_archives_non_best(
    wired_review_queue: ReviewQueueService,
    track_repo: TrackRepository,
    duplicate_repo: DuplicateRepository,
    job_repo: JobRepository,
    library_id: UUID,
    track_id: UUID,
) -> None:
    best = _make_track(library_id, track_id, zone=LibraryZone.LIBRARY, needs_review=False)
    track_repo.upsert(best)
    loser_id = UUID("01800000-0000-7000-8000-00000000beef")
    track_repo.upsert(
        _make_track(
            library_id,
            loser_id,
            zone=LibraryZone.LIBRARY,
            needs_review=False,
            file_path="C:/library/loser.mp3",
            file_name="loser.mp3",
        )
    )
    group = DuplicateGroup(
        id=UUID("01800000-0000-7000-8000-0000000000aa"),
        library_id=library_id,
        match_type=MatchType.FINGERPRINT,
        match_confidence=0.95,
        track_count=2,
        detected_at=_NOW,
        best_track_id=track_id,
    )
    duplicate_repo.save_group(
        group,
        [
            DuplicateMember(group.id, track_id, quality_score=90, zone="library", is_best=True),
            DuplicateMember(group.id, loser_id, quality_score=40, zone="library"),
        ],
    )
    review_id = wired_review_queue.create_item(
        ReviewItemCreate(
            library_id=library_id,
            review_type=ReviewType.POSSIBLE_DUPLICATE,
            title="Possible duplicate",
            track_id=track_id,
            duplicate_group_id=group.id,
        ),
        now=_NOW,
    )

    wired_review_queue.approve(review_id, now=_NOW)

    resolved = duplicate_repo.get_group(group.id)
    assert resolved is not None
    assert resolved.status is GroupStatus.RESOLVED
    assert resolved.resolution is GroupResolution.KEPT_BEST
    assert _pending_organize_jobs(job_repo) == [
        {"track_id": str(loser_id), "target_zone": "archive"}
    ]
