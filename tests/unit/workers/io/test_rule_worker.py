"""Unit tests for RuleWorker."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Engine

from musicvault.core.event_bus import EventBus
from musicvault.db.repositories.artist_repo import ArtistRepository
from musicvault.db.repositories.duplicate_repo import DuplicateRepository
from musicvault.db.repositories.job_repo import JobRepository
from musicvault.db.repositories.review_repo import ReviewRepository
from musicvault.db.repositories.rule_repo import RuleRepository
from musicvault.db.repositories.track_repo import TrackRepository
from musicvault.db.uuid_utils import generate_uuid7
from musicvault.models.entities.duplicate_group import (
    DuplicateGroup,
    DuplicateMember,
    MatchType,
)
from musicvault.models.entities.job import Job, JobStatus, JobType
from musicvault.models.entities.review_item import ReviewStatus, ReviewType
from musicvault.models.entities.track import LibraryZone, Track
from musicvault.services.job_queue_service import JobQueueService
from musicvault.services.review_queue_service import ReviewQueueService
from musicvault.services.rules_engine import RulesEngine
from musicvault.workers.io.rule_worker import RuleWorker

_NOW = datetime(2026, 7, 16, tzinfo=UTC)


def _make_track(library_id: UUID, track_id: UUID, **overrides: object) -> Track:
    defaults: dict[str, object] = {
        "id": track_id,
        "library_id": library_id,
        "zone": LibraryZone.INCOMING,
        "file_path": "C:/incoming/low.mp3",
        "file_name": "low.mp3",
        "file_size": 1024,
        "file_modified": _NOW,
        "created_at": _NOW,
        "updated_at": _NOW,
        "codec": "mp3",
        "bitrate": 96,
    }
    defaults.update(overrides)
    return Track(**defaults)  # type: ignore[arg-type]


def test_execute_seeds_defaults_and_flags_low_bitrate(
    track_repo: TrackRepository,
    job_queue: JobQueueService,
    job_repo: JobRepository,
    review_repo: ReviewRepository,
    rule_repo: RuleRepository,
    engine: Engine,
    library_id: UUID,
    track_id: UUID,
) -> None:
    track_repo.upsert(_make_track(library_id, track_id))
    event_bus = EventBus()
    rules = RulesEngine(
        rule_repo,
        track_repo,
        ArtistRepository(engine),
        ReviewQueueService(review_repo, track_repo, event_bus),
        event_bus,
    )
    job_id = job_queue.enqueue(
        JobType.EVALUATE_RULES, library_id, {"track_id": str(track_id)}, now=_NOW
    )
    job_repo.update_status(job_id, JobStatus.RUNNING)

    RuleWorker(track_repo, rules, DuplicateRepository(engine), job_queue).execute(
        Job(
            id=job_id,
            library_id=library_id,
            job_type=JobType.EVALUATE_RULES,
            status=JobStatus.RUNNING,
            payload={"track_id": str(track_id)},
            created_at=_NOW,
        )
    )

    assert job_repo.get(job_id).status is JobStatus.COMPLETED  # type: ignore[union-attr]
    assert len(rule_repo.list_by_library(library_id)) == 3
    pending = review_repo.list_by_status(ReviewStatus.PENDING, library_id=library_id)
    assert any(item.review_type is ReviewType.LOW_QUALITY for item in pending)


def test_execute_archive_mp3_rule_matches_when_lossless_duplicate_exists(
    track_repo: TrackRepository,
    job_queue: JobQueueService,
    job_repo: JobRepository,
    review_repo: ReviewRepository,
    rule_repo: RuleRepository,
    duplicate_repo: DuplicateRepository,
    engine: Engine,
    library_id: UUID,
    track_id: UUID,
) -> None:
    """Phase 9 un-stubs `has_lossless_duplicate`: an MP3 sharing an open
    duplicate group with a FLAC now triggers the archive-MP3 default rule,
    which parks a rule_action review item (real zone moves = Phase 10)."""
    flac_id = generate_uuid7()
    track_repo.upsert(_make_track(library_id, track_id, codec="mp3", bitrate=320))
    track_repo.upsert(
        _make_track(
            library_id,
            flac_id,
            codec="flac",
            bitrate=None,
            is_lossless=True,
            file_path="C:/library/high.flac",
            file_name="high.flac",
        )
    )
    group_id = generate_uuid7()
    duplicate_repo.save_group(
        DuplicateGroup(
            id=group_id,
            library_id=library_id,
            match_type=MatchType.FINGERPRINT,
            match_confidence=0.95,
            best_track_id=flac_id,
            track_count=2,
            detected_at=_NOW,
        ),
        [
            DuplicateMember(
                group_id=group_id,
                track_id=flac_id,
                quality_score=95,
                zone="library",
                is_best=True,
            ),
            DuplicateMember(
                group_id=group_id, track_id=track_id, quality_score=70, zone="incoming"
            ),
        ],
    )
    event_bus = EventBus()
    rules = RulesEngine(
        rule_repo,
        track_repo,
        ArtistRepository(engine),
        ReviewQueueService(review_repo, track_repo, event_bus),
        event_bus,
    )
    job_id = job_queue.enqueue(
        JobType.EVALUATE_RULES, library_id, {"track_id": str(track_id)}, now=_NOW
    )
    job_repo.update_status(job_id, JobStatus.RUNNING)

    RuleWorker(track_repo, rules, duplicate_repo, job_queue).execute(
        Job(
            id=job_id,
            library_id=library_id,
            job_type=JobType.EVALUATE_RULES,
            status=JobStatus.RUNNING,
            payload={"track_id": str(track_id)},
            created_at=_NOW,
        )
    )

    assert job_repo.get(job_id).status is JobStatus.COMPLETED  # type: ignore[union-attr]
    pending = review_repo.list_by_status(ReviewStatus.PENDING, library_id=library_id)
    rule_items = [item for item in pending if item.review_type is ReviewType.RULE_ACTION]
    assert any("Archive MP3" in item.title for item in rule_items)


def test_execute_enqueues_organize_to_staging_for_incoming_tracks(
    track_repo: TrackRepository,
    job_queue: JobQueueService,
    job_repo: JobRepository,
    review_repo: ReviewRepository,
    rule_repo: RuleRepository,
    engine: Engine,
    library_id: UUID,
    track_id: UUID,
) -> None:
    """Phase 10: rules are the last analysis stage — an incoming track then
    moves to staging via an organize_file job."""
    track_repo.upsert(_make_track(library_id, track_id, bitrate=320))
    event_bus = EventBus()
    rules = RulesEngine(
        rule_repo,
        track_repo,
        ArtistRepository(engine),
        ReviewQueueService(review_repo, track_repo, event_bus),
        event_bus,
    )
    job_id = job_queue.enqueue(
        JobType.EVALUATE_RULES, library_id, {"track_id": str(track_id)}, now=_NOW
    )
    job_repo.update_status(job_id, JobStatus.RUNNING)

    RuleWorker(track_repo, rules, DuplicateRepository(engine), job_queue).execute(
        Job(
            id=job_id,
            library_id=library_id,
            job_type=JobType.EVALUATE_RULES,
            status=JobStatus.RUNNING,
            payload={"track_id": str(track_id)},
            created_at=_NOW,
        )
    )

    organize = [
        job
        for job in job_repo.list_by_status(JobStatus.PENDING, library_id=library_id)
        if job.job_type is JobType.ORGANIZE_FILE
    ]
    assert len(organize) == 1
    assert organize[0].payload == {"track_id": str(track_id), "target_zone": "staging"}
    assert organize[0].parent_job_id == job_id


def test_execute_does_not_enqueue_organize_for_non_incoming_tracks(
    track_repo: TrackRepository,
    job_queue: JobQueueService,
    job_repo: JobRepository,
    review_repo: ReviewRepository,
    rule_repo: RuleRepository,
    engine: Engine,
    library_id: UUID,
    track_id: UUID,
) -> None:
    track_repo.upsert(_make_track(library_id, track_id, zone=LibraryZone.LIBRARY, bitrate=320))
    event_bus = EventBus()
    rules = RulesEngine(
        rule_repo,
        track_repo,
        ArtistRepository(engine),
        ReviewQueueService(review_repo, track_repo, event_bus),
        event_bus,
    )
    job_id = job_queue.enqueue(
        JobType.EVALUATE_RULES, library_id, {"track_id": str(track_id)}, now=_NOW
    )
    job_repo.update_status(job_id, JobStatus.RUNNING)

    RuleWorker(track_repo, rules, DuplicateRepository(engine), job_queue).execute(
        Job(
            id=job_id,
            library_id=library_id,
            job_type=JobType.EVALUATE_RULES,
            status=JobStatus.RUNNING,
            payload={"track_id": str(track_id)},
            created_at=_NOW,
        )
    )

    organize = [
        job
        for job in job_repo.list_by_status(JobStatus.PENDING, library_id=library_id)
        if job.job_type is JobType.ORGANIZE_FILE
    ]
    assert organize == []


def test_execute_marks_failed_when_track_missing(
    track_repo: TrackRepository,
    job_queue: JobQueueService,
    job_repo: JobRepository,
    review_repo: ReviewRepository,
    rule_repo: RuleRepository,
    engine: Engine,
    library_id: UUID,
) -> None:
    missing = generate_uuid7()
    event_bus = EventBus()
    rules = RulesEngine(
        rule_repo,
        track_repo,
        ArtistRepository(engine),
        ReviewQueueService(review_repo, track_repo, event_bus),
        event_bus,
    )
    job_id = job_queue.enqueue(
        JobType.EVALUATE_RULES, library_id, {"track_id": str(missing)}, now=_NOW
    )
    job_repo.update_status(job_id, JobStatus.RUNNING)

    RuleWorker(track_repo, rules, DuplicateRepository(engine), job_queue).execute(
        Job(
            id=job_id,
            library_id=library_id,
            job_type=JobType.EVALUATE_RULES,
            status=JobStatus.RUNNING,
            payload={"track_id": str(missing)},
            created_at=_NOW,
        )
    )

    status = job_repo.get(job_id)
    assert status is not None
    assert status.status is JobStatus.RETRY
    assert status.error_message is not None
    assert "not found" in status.error_message
