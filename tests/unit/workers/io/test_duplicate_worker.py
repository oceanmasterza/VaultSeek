"""Unit tests for DuplicateWorker."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Engine, insert

from vaultseek.db.repositories.album_repo import AlbumRepository
from vaultseek.db.repositories.duplicate_repo import DuplicateRepository
from vaultseek.db.repositories.file_identity_repo import FileIdentityRepository
from vaultseek.db.repositories.job_repo import JobRepository
from vaultseek.db.repositories.review_repo import ReviewRepository
from vaultseek.db.repositories.track_repo import TrackRepository
from vaultseek.db.tables import albums
from vaultseek.db.uuid_utils import generate_uuid7, uuid_to_blob
from vaultseek.models.entities.duplicate_group import MatchType
from vaultseek.models.entities.job import Job, JobStatus, JobType
from vaultseek.models.entities.review_item import ReviewStatus, ReviewType
from vaultseek.models.entities.track import LibraryZone, Track
from vaultseek.models.services.duplicate_matcher import DuplicateMatcher
from vaultseek.models.services.quality_scorer import DEFAULT_WEIGHTS, QualityScorer
from vaultseek.models.value_objects.file_identity import FileIdentity
from vaultseek.services.job_queue_service import JobQueueService
from vaultseek.services.review_queue_service import ReviewQueueService
from vaultseek.workers.io.duplicate_worker import DuplicateWorker

_NOW = datetime(2026, 7, 17, tzinfo=UTC)


def _make_track(library_id: UUID, track_id: UUID, **overrides: object) -> Track:
    defaults: dict[str, object] = {
        "id": track_id,
        "library_id": library_id,
        "zone": LibraryZone.INCOMING,
        "file_path": f"C:/incoming/{track_id}.mp3",
        "file_name": f"{track_id}.mp3",
        "file_size": 1024,
        "file_modified": _NOW,
        "created_at": _NOW,
        "updated_at": _NOW,
        "codec": "mp3",
        "bitrate": 320,
    }
    defaults.update(overrides)
    return Track(**defaults)  # type: ignore[arg-type]


def _make_identity(track_id: UUID, **overrides: object) -> FileIdentity:
    defaults: dict[str, object] = {
        "track_id": track_id,
        "content_hash_sha256": f"hash-{track_id}",
        "file_size": 1024,
        "file_modified": _NOW,
    }
    defaults.update(overrides)
    return FileIdentity(**defaults)  # type: ignore[arg-type]


def _insert_album(engine: Engine, title: str = "Same Album") -> UUID:
    album_id = generate_uuid7()
    with engine.begin() as conn:
        conn.execute(
            insert(albums).values(
                id=uuid_to_blob(album_id),
                title=title,
                sort_title=title,
                created_at="2026-07-17T00:00:00",
                updated_at="2026-07-17T00:00:00",
            )
        )
    return album_id


def _worker(
    track_repo: TrackRepository,
    file_identity_repo: FileIdentityRepository,
    duplicate_repo: DuplicateRepository,
    review_queue: ReviewQueueService,
    job_queue: JobQueueService,
    *,
    engine: Engine | None = None,
) -> DuplicateWorker:
    return DuplicateWorker(
        track_repo,
        file_identity_repo,
        duplicate_repo,
        DuplicateMatcher(QualityScorer(DEFAULT_WEIGHTS)),
        review_queue,
        job_queue,
        album_repo=AlbumRepository(engine) if engine is not None else None,
    )


def _run_job(
    worker: DuplicateWorker,
    job_queue: JobQueueService,
    job_repo: JobRepository,
    library_id: UUID,
    track_id: UUID,
) -> UUID:
    job_id = job_queue.enqueue(
        JobType.DETECT_DUPLICATES, library_id, {"track_id": str(track_id)}, now=_NOW
    )
    job_repo.update_status(job_id, JobStatus.RUNNING)
    worker.execute(
        Job(
            id=job_id,
            library_id=library_id,
            job_type=JobType.DETECT_DUPLICATES,
            status=JobStatus.RUNNING,
            payload={"track_id": str(track_id)},
            created_at=_NOW,
        )
    )
    return job_id


def test_execute_groups_fingerprint_duplicates_and_flags_review(
    track_repo: TrackRepository,
    file_identity_repo: FileIdentityRepository,
    duplicate_repo: DuplicateRepository,
    review_repo: ReviewRepository,
    review_queue: ReviewQueueService,
    job_queue: JobQueueService,
    job_repo: JobRepository,
    engine: Engine,
    library_id: UUID,
    track_id: UUID,
) -> None:
    album_id = _insert_album(engine)
    flac_id = generate_uuid7()
    track_repo.upsert(
        _make_track(library_id, track_id, codec="mp3", bitrate=320, album_id=album_id)
    )
    track_repo.upsert(
        _make_track(
            library_id,
            flac_id,
            codec="flac",
            bitrate=None,
            is_lossless=True,
            bit_depth=16,
            album_id=album_id,
            file_path=f"C:/library/{flac_id}.flac",
        )
    )
    file_identity_repo.upsert(_make_identity(track_id, fingerprint_hash="fp-1"))
    file_identity_repo.upsert(_make_identity(flac_id, fingerprint_hash="fp-1"))
    worker = _worker(
        track_repo, file_identity_repo, duplicate_repo, review_queue, job_queue, engine=engine
    )

    job_id = _run_job(worker, job_queue, job_repo, library_id, track_id)

    assert job_repo.get(job_id).status is JobStatus.COMPLETED  # type: ignore[union-attr]
    groups = duplicate_repo.list_open_by_library(library_id)
    assert len(groups) == 1
    group = groups[0]
    assert group.match_type is MatchType.FINGERPRINT
    assert group.best_track_id == flac_id
    members = duplicate_repo.get_members(group.id)
    assert {m.track_id for m in members} == {track_id, flac_id}

    assert track_repo.get_by_id(track_id).quality_score == 70  # type: ignore[union-attr]
    assert track_repo.get_by_id(flac_id).quality_score == 95  # type: ignore[union-attr]

    pending = review_repo.list_by_status(ReviewStatus.PENDING, library_id=library_id)
    duplicates = [i for i in pending if i.review_type is ReviewType.POSSIBLE_DUPLICATE]
    assert len(duplicates) == 1
    assert duplicates[0].duplicate_group_id == group.id

    assert duplicate_repo.has_lossless_duplicate(track_id) is True

    rule_jobs = [
        job
        for job in job_repo.list_by_status(JobStatus.PENDING)
        if job.job_type is JobType.EVALUATE_RULES
    ]
    assert len(rule_jobs) == 1
    assert rule_jobs[0].payload["track_id"] == str(track_id)


def test_execute_ignores_fingerprint_match_on_different_albums(
    track_repo: TrackRepository,
    file_identity_repo: FileIdentityRepository,
    duplicate_repo: DuplicateRepository,
    review_queue: ReviewQueueService,
    job_queue: JobQueueService,
    job_repo: JobRepository,
    engine: Engine,
    library_id: UUID,
    track_id: UUID,
) -> None:
    album_a = _insert_album(engine, "Album A")
    album_b = _insert_album(engine, "Album B")
    other_id = generate_uuid7()
    track_repo.upsert(
        _make_track(
            library_id,
            track_id,
            album_id=album_a,
            mb_recording_id="same-recording",
            overall_confidence=0.95,
        )
    )
    track_repo.upsert(
        _make_track(
            library_id,
            other_id,
            album_id=album_b,
            mb_recording_id="same-recording",
            file_path=f"C:/incoming/{other_id}.mp3",
            overall_confidence=0.95,
        )
    )
    file_identity_repo.upsert(_make_identity(track_id, fingerprint_hash="fp-shared"))
    file_identity_repo.upsert(_make_identity(other_id, fingerprint_hash="fp-shared"))
    worker = _worker(
        track_repo, file_identity_repo, duplicate_repo, review_queue, job_queue, engine=engine
    )

    _run_job(worker, job_queue, job_repo, library_id, track_id)

    assert duplicate_repo.list_open_by_library(library_id) == []
    assert review_queue.get_pending(library_id) == []


def test_execute_auto_keeps_best_for_confident_same_album_duplicates(
    track_repo: TrackRepository,
    file_identity_repo: FileIdentityRepository,
    duplicate_repo: DuplicateRepository,
    review_queue: ReviewQueueService,
    job_queue: JobQueueService,
    job_repo: JobRepository,
    engine: Engine,
    library_id: UUID,
    track_id: UUID,
) -> None:
    album_id = _insert_album(engine)
    flac_id = generate_uuid7()
    track_repo.upsert(
        _make_track(
            library_id,
            track_id,
            codec="mp3",
            bitrate=320,
            album_id=album_id,
            overall_confidence=0.95,
            needs_review=False,
        )
    )
    track_repo.upsert(
        _make_track(
            library_id,
            flac_id,
            codec="flac",
            bitrate=None,
            is_lossless=True,
            bit_depth=16,
            album_id=album_id,
            overall_confidence=0.95,
            needs_review=False,
            file_path=f"C:/library/{flac_id}.flac",
        )
    )
    file_identity_repo.upsert(_make_identity(track_id, fingerprint_hash="fp-1"))
    file_identity_repo.upsert(_make_identity(flac_id, fingerprint_hash="fp-1"))
    worker = _worker(
        track_repo, file_identity_repo, duplicate_repo, review_queue, job_queue, engine=engine
    )

    _run_job(worker, job_queue, job_repo, library_id, track_id)

    assert duplicate_repo.list_open_by_library(library_id) == []
    assert review_queue.get_pending(library_id) == []
    archive_jobs = [
        job
        for job in job_repo.list_by_status(JobStatus.PENDING, library_id=library_id)
        if job.job_type is JobType.ORGANIZE_FILE
        and job.payload.get("target_zone") == "archive"
    ]
    assert len(archive_jobs) == 1
    assert archive_jobs[0].payload["track_id"] == str(track_id)


def test_execute_prefers_hash_match_over_weaker_tiers(
    track_repo: TrackRepository,
    file_identity_repo: FileIdentityRepository,
    duplicate_repo: DuplicateRepository,
    review_queue: ReviewQueueService,
    job_queue: JobQueueService,
    job_repo: JobRepository,
    engine: Engine,
    library_id: UUID,
    track_id: UUID,
) -> None:
    other_id = generate_uuid7()
    track_repo.upsert(_make_track(library_id, track_id, mb_recording_id="mbid-1"))
    track_repo.upsert(
        _make_track(
            library_id,
            other_id,
            mb_recording_id="mbid-1",
            file_path=f"C:/incoming/{other_id}.mp3",
        )
    )
    file_identity_repo.upsert(
        _make_identity(track_id, content_hash_sha256="same", fingerprint_hash="fp-1")
    )
    file_identity_repo.upsert(
        _make_identity(other_id, content_hash_sha256="same", fingerprint_hash="fp-1")
    )
    worker = _worker(
        track_repo, file_identity_repo, duplicate_repo, review_queue, job_queue, engine=engine
    )

    _run_job(worker, job_queue, job_repo, library_id, track_id)

    groups = duplicate_repo.list_open_by_library(library_id)
    assert len(groups) == 1
    assert groups[0].match_type is MatchType.HASH
    assert groups[0].match_confidence == 1.0


def test_execute_is_idempotent_on_redetection(
    track_repo: TrackRepository,
    file_identity_repo: FileIdentityRepository,
    duplicate_repo: DuplicateRepository,
    review_repo: ReviewRepository,
    review_queue: ReviewQueueService,
    job_queue: JobQueueService,
    job_repo: JobRepository,
    engine: Engine,
    library_id: UUID,
    track_id: UUID,
) -> None:
    album_id = _insert_album(engine)
    other_id = generate_uuid7()
    track_repo.upsert(_make_track(library_id, track_id, album_id=album_id))
    track_repo.upsert(
        _make_track(
            library_id, other_id, album_id=album_id, file_path=f"C:/incoming/{other_id}.mp3"
        )
    )
    file_identity_repo.upsert(_make_identity(track_id, fingerprint_hash="fp-1"))
    file_identity_repo.upsert(_make_identity(other_id, fingerprint_hash="fp-1"))
    worker = _worker(
        track_repo, file_identity_repo, duplicate_repo, review_queue, job_queue, engine=engine
    )

    _run_job(worker, job_queue, job_repo, library_id, track_id)
    _run_job(worker, job_queue, job_repo, library_id, track_id)

    assert len(duplicate_repo.list_open_by_library(library_id)) == 1
    pending = review_repo.list_by_status(ReviewStatus.PENDING, library_id=library_id)
    duplicates = [i for i in pending if i.review_type is ReviewType.POSSIBLE_DUPLICATE]
    assert len(duplicates) == 1


def test_execute_without_matches_creates_no_group_but_still_chains_rules(
    track_repo: TrackRepository,
    file_identity_repo: FileIdentityRepository,
    duplicate_repo: DuplicateRepository,
    review_queue: ReviewQueueService,
    job_queue: JobQueueService,
    job_repo: JobRepository,
    engine: Engine,
    library_id: UUID,
    track_id: UUID,
) -> None:
    track_repo.upsert(_make_track(library_id, track_id))
    file_identity_repo.upsert(_make_identity(track_id, fingerprint_hash="fp-unique"))
    worker = _worker(
        track_repo, file_identity_repo, duplicate_repo, review_queue, job_queue, engine=engine
    )

    job_id = _run_job(worker, job_queue, job_repo, library_id, track_id)

    assert job_repo.get(job_id).status is JobStatus.COMPLETED  # type: ignore[union-attr]
    assert duplicate_repo.list_open_by_library(library_id) == []
    rule_jobs = [
        job
        for job in job_repo.list_by_status(JobStatus.PENDING)
        if job.job_type is JobType.EVALUATE_RULES
    ]
    assert len(rule_jobs) == 1


def test_execute_marks_failed_when_track_missing(
    track_repo: TrackRepository,
    file_identity_repo: FileIdentityRepository,
    duplicate_repo: DuplicateRepository,
    review_queue: ReviewQueueService,
    job_queue: JobQueueService,
    job_repo: JobRepository,
    engine: Engine,
    library_id: UUID,
) -> None:
    missing = generate_uuid7()
    worker = _worker(
        track_repo, file_identity_repo, duplicate_repo, review_queue, job_queue, engine=engine
    )

    job_id = _run_job(worker, job_queue, job_repo, library_id, missing)

    status = job_repo.get(job_id)
    assert status is not None
    assert status.status is JobStatus.RETRY
    assert status.error_message is not None
    assert "not found" in status.error_message
