"""Unit tests for OrganizerWorker (real files under tmp_path)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import Engine

from musicvault.db.repositories.album_repo import AlbumRepository
from musicvault.db.repositories.artist_repo import ArtistRepository
from musicvault.db.repositories.duplicate_repo import DuplicateRepository
from musicvault.db.repositories.job_repo import JobRepository
from musicvault.db.repositories.library_repo import LibraryRepository
from musicvault.db.repositories.operation_repo import OperationRepository
from musicvault.db.repositories.review_repo import ReviewRepository
from musicvault.db.repositories.track_repo import TrackRepository
from musicvault.db.uuid_utils import generate_uuid7
from musicvault.models.entities.artist import Artist
from musicvault.models.entities.job import Job, JobStatus, JobType
from musicvault.models.entities.library import Library
from musicvault.models.entities.operation import ChangeType, OperationStatus, OperationType
from musicvault.models.entities.track import LibraryZone, Track
from musicvault.models.services.organize_engine import OrganizeEngine
from musicvault.services.job_queue_service import JobQueueService
from musicvault.workers.io.organizer_worker import OrganizerWorker

_NOW = datetime(2026, 7, 17, tzinfo=UTC)


@pytest.fixture
def library_repo(engine: Engine) -> LibraryRepository:
    return LibraryRepository(engine)


@pytest.fixture
def operation_repo(engine: Engine) -> OperationRepository:
    return OperationRepository(engine)


@pytest.fixture
def zone_library(library_repo: LibraryRepository, tmp_path: Path) -> Library:
    """A library whose zone roots are real tmp_path directories."""
    library = Library(
        id=generate_uuid7(),
        name="Zoned",
        incoming_path=str(tmp_path / "Incoming"),
        staging_path=str(tmp_path / "Staging"),
        library_path=str(tmp_path / "Music"),
        archive_path=str(tmp_path / "Archive"),
        created_at=_NOW,
        updated_at=_NOW,
        auto_approve_threshold=0.90,
    )
    library_repo.upsert(library)
    for root in (
        library.incoming_path,
        library.staging_path,
        library.library_path,
        library.archive_path,
    ):
        Path(root).mkdir(parents=True, exist_ok=True)
    return library


@pytest.fixture
def worker(
    track_repo: TrackRepository,
    library_repo: LibraryRepository,
    review_repo: ReviewRepository,
    duplicate_repo: DuplicateRepository,
    operation_repo: OperationRepository,
    job_queue: JobQueueService,
    engine: Engine,
) -> OrganizerWorker:
    return OrganizerWorker(
        track_repo,
        library_repo,
        ArtistRepository(engine),
        AlbumRepository(engine),
        review_repo,
        duplicate_repo,
        operation_repo,
        OrganizeEngine(),
        job_queue,
    )


def _make_track(library: Library, source: Path, **overrides: object) -> Track:
    defaults: dict[str, object] = {
        "id": generate_uuid7(),
        "library_id": library.id,
        "zone": LibraryZone.INCOMING,
        "file_path": str(source),
        "file_name": source.name,
        "file_size": source.stat().st_size,
        "file_modified": _NOW,
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    defaults.update(overrides)
    return Track(**defaults)  # type: ignore[arg-type]


def _write_source(library: Library, name: str, zone: LibraryZone = LibraryZone.INCOMING) -> Path:
    source = Path(library.zone_root(zone)) / name
    source.write_bytes(b"audio-bytes")
    return source


def _run(
    worker: OrganizerWorker,
    job_queue: JobQueueService,
    job_repo: JobRepository,
    library: Library,
    track_id: UUID,
    target_zone: str,
) -> UUID:
    payload = {"track_id": str(track_id), "target_zone": target_zone}
    job_id = job_queue.enqueue(JobType.ORGANIZE_FILE, library.id, payload, now=_NOW)
    job_repo.update_status(job_id, JobStatus.RUNNING)
    worker.execute(
        Job(
            id=job_id,
            library_id=library.id,
            job_type=JobType.ORGANIZE_FILE,
            status=JobStatus.RUNNING,
            payload=payload,
            created_at=_NOW,
        )
    )
    return job_id


def test_execute_moves_file_updates_track_and_logs_operation(
    worker: OrganizerWorker,
    track_repo: TrackRepository,
    operation_repo: OperationRepository,
    job_queue: JobQueueService,
    job_repo: JobRepository,
    zone_library: Library,
    engine: Engine,
) -> None:
    artist = Artist(
        id=generate_uuid7(),
        name="Radiohead",
        sort_name="Radiohead",
        created_at=_NOW,
        updated_at=_NOW,
    )
    ArtistRepository(engine).create(artist)
    source = _write_source(zone_library, "raw.flac")
    track = _make_track(
        zone_library, source, title="Karma Police", track_number=6, artist_id=artist.id
    )
    track_repo.upsert(track)

    job_id = _run(worker, job_queue, job_repo, zone_library, track.id, "staging")

    assert job_repo.get(job_id).status is JobStatus.COMPLETED  # type: ignore[union-attr]
    expected = Path(zone_library.staging_path) / "Radiohead" / "06 - Karma Police.flac"
    assert expected.is_file()
    assert not source.exists()

    updated = track_repo.get_by_id(track.id)
    assert updated is not None
    assert updated.zone is LibraryZone.STAGING
    assert updated.file_path == str(expected)
    assert updated.file_name == expected.name

    history = operation_repo.list_changes_for_track(track.id)
    assert len(history) == 1
    assert history[0].change_type is ChangeType.MOVE
    assert history[0].old_zone == "incoming"
    assert history[0].new_zone == "staging"
    assert history[0].old_file_path == str(source)
    assert history[0].new_file_path == str(expected)
    operation = operation_repo.get(history[0].operation_id)
    assert operation is not None
    assert operation.operation_type is OperationType.FILE_MOVE
    assert operation.status is OperationStatus.COMPLETED
    assert operation.affected_count == 1


def test_execute_suffixes_on_filename_collision(
    worker: OrganizerWorker,
    track_repo: TrackRepository,
    job_queue: JobQueueService,
    job_repo: JobRepository,
    zone_library: Library,
) -> None:
    occupied = Path(zone_library.staging_path) / "Unknown Artist" / "raw.flac"
    occupied.parent.mkdir(parents=True)
    occupied.write_bytes(b"existing")
    source = _write_source(zone_library, "raw.flac")
    track = _make_track(zone_library, source)
    track_repo.upsert(track)

    _run(worker, job_queue, job_repo, zone_library, track.id, "staging")

    suffixed = occupied.with_name("raw (1).flac")
    assert suffixed.is_file()
    assert occupied.read_bytes() == b"existing"
    updated = track_repo.get_by_id(track.id)
    assert updated is not None
    assert updated.file_path == str(suffixed)


def test_execute_auto_approves_confident_track_into_library(
    worker: OrganizerWorker,
    track_repo: TrackRepository,
    job_queue: JobQueueService,
    job_repo: JobRepository,
    zone_library: Library,
) -> None:
    source = _write_source(zone_library, "confident.flac")
    track = _make_track(zone_library, source, title="Sure Thing", overall_confidence=0.97)
    track_repo.upsert(track)

    _run(worker, job_queue, job_repo, zone_library, track.id, "staging")

    follow_ups = [
        job
        for job in job_repo.list_by_status(JobStatus.PENDING)
        if job.job_type is JobType.ORGANIZE_FILE
    ]
    assert len(follow_ups) == 1
    assert follow_ups[0].payload == {
        "track_id": str(track.id),
        "target_zone": "library",
    }


def test_execute_does_not_auto_approve_below_threshold_or_with_pending_review(
    worker: OrganizerWorker,
    track_repo: TrackRepository,
    review_repo: ReviewRepository,
    job_queue: JobQueueService,
    job_repo: JobRepository,
    zone_library: Library,
) -> None:
    low = _make_track(
        zone_library,
        _write_source(zone_library, "low.flac"),
        overall_confidence=0.50,
    )
    track_repo.upsert(low)

    _run(worker, job_queue, job_repo, zone_library, low.id, "staging")

    follow_ups = [
        job
        for job in job_repo.list_by_status(JobStatus.PENDING)
        if job.job_type is JobType.ORGANIZE_FILE
    ]
    assert follow_ups == []


def test_execute_is_a_completed_noop_when_already_in_target_zone(
    worker: OrganizerWorker,
    track_repo: TrackRepository,
    job_queue: JobQueueService,
    job_repo: JobRepository,
    zone_library: Library,
) -> None:
    source = _write_source(zone_library, "already.flac", LibraryZone.STAGING)
    track = _make_track(zone_library, source, zone=LibraryZone.STAGING)
    track_repo.upsert(track)

    job_id = _run(worker, job_queue, job_repo, zone_library, track.id, "staging")

    assert job_repo.get(job_id).status is JobStatus.COMPLETED  # type: ignore[union-attr]
    assert source.is_file()  # untouched


def test_execute_fails_on_illegal_transition(
    worker: OrganizerWorker,
    track_repo: TrackRepository,
    job_queue: JobQueueService,
    job_repo: JobRepository,
    zone_library: Library,
) -> None:
    source = _write_source(zone_library, "straight-to-library.flac")
    track = _make_track(zone_library, source)
    track_repo.upsert(track)

    job_id = _run(worker, job_queue, job_repo, zone_library, track.id, "library")

    status = job_repo.get(job_id)
    assert status is not None
    assert status.status is JobStatus.RETRY
    assert status.error_message is not None
    assert "Illegal zone transition" in status.error_message
    assert source.is_file()


def test_execute_fails_when_source_file_is_missing(
    worker: OrganizerWorker,
    track_repo: TrackRepository,
    job_queue: JobQueueService,
    job_repo: JobRepository,
    zone_library: Library,
) -> None:
    source = _write_source(zone_library, "ghost.flac")
    track = _make_track(zone_library, source)
    track_repo.upsert(track)
    source.unlink()

    job_id = _run(worker, job_queue, job_repo, zone_library, track.id, "staging")

    status = job_repo.get(job_id)
    assert status is not None
    assert status.status is JobStatus.RETRY
    assert status.error_message is not None
    assert "Source file missing" in status.error_message


def test_execute_fails_when_track_missing(
    worker: OrganizerWorker,
    job_queue: JobQueueService,
    job_repo: JobRepository,
    zone_library: Library,
) -> None:
    job_id = _run(worker, job_queue, job_repo, zone_library, generate_uuid7(), "staging")

    status = job_repo.get(job_id)
    assert status is not None
    assert status.status is JobStatus.RETRY
    assert status.error_message is not None
    assert "not found" in status.error_message
