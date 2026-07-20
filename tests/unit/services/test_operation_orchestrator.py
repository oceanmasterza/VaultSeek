"""Unit tests for vaultseek.services.operation_orchestrator."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import Engine

from vaultseek.core.exceptions import OperationError, RollbackError
from vaultseek.db.repositories.album_repo import AlbumRepository
from vaultseek.db.repositories.artist_repo import ArtistRepository
from vaultseek.db.repositories.library_repo import LibraryRepository
from vaultseek.db.repositories.operation_repo import OperationRepository
from vaultseek.db.repositories.track_repo import TrackRepository
from vaultseek.db.uuid_utils import generate_uuid7
from vaultseek.models.entities.job import JobStatus, JobType
from vaultseek.models.entities.library import Library
from vaultseek.models.entities.operation import OperationStatus, OperationType
from vaultseek.models.entities.track import LibraryZone, Track
from vaultseek.models.services.organize_engine import OrganizeEngine
from vaultseek.services.dto.operation_dto import OperationRequest
from vaultseek.services.job_queue_service import JobQueueService
from vaultseek.services.operation_orchestrator import OperationOrchestrator
from vaultseek.workers.io.organizer_worker import OrganizerWorker

_NOW = datetime(2026, 7, 18, tzinfo=UTC)


@pytest.fixture
def zone_library(tmp_path: Path, library_repo: LibraryRepository, library_id: UUID) -> Library:
    library = Library(
        id=library_id,
        name="Test",
        incoming_path=str(tmp_path / "incoming"),
        staging_path=str(tmp_path / "staging"),
        library_path=str(tmp_path / "library"),
        archive_path=str(tmp_path / "archive"),
        created_at=_NOW,
        updated_at=_NOW,
        watch_enabled=False,
        auto_approve_threshold=0.99,  # keep auto-approve from firing in these tests
    )
    for path in (
        library.incoming_path,
        library.staging_path,
        library.library_path,
        library.archive_path,
    ):
        Path(path).mkdir(parents=True)
    library_repo.upsert(library)
    return library


@pytest.fixture
def library_repo(engine: Engine) -> LibraryRepository:
    return LibraryRepository(engine)


@pytest.fixture
def operation_repo(engine: Engine) -> OperationRepository:
    return OperationRepository(engine)


@pytest.fixture
def orchestrator(
    operation_repo: OperationRepository,
    track_repo: TrackRepository,
    library_repo: LibraryRepository,
    engine: Engine,
    job_queue: JobQueueService,
) -> OperationOrchestrator:
    return OperationOrchestrator(
        operation_repo,
        track_repo,
        library_repo,
        ArtistRepository(engine),
        AlbumRepository(engine),
        OrganizeEngine(),
        job_queue=job_queue,
    )


@pytest.fixture
def organizer(
    track_repo: TrackRepository,
    library_repo: LibraryRepository,
    operation_repo: OperationRepository,
    engine: Engine,
    review_repo: object,
    duplicate_repo: object,
    job_queue: JobQueueService,
) -> OrganizerWorker:
    from vaultseek.db.repositories.duplicate_repo import DuplicateRepository
    from vaultseek.db.repositories.review_repo import ReviewRepository

    assert isinstance(review_repo, ReviewRepository)
    assert isinstance(duplicate_repo, DuplicateRepository)
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
        "title": "Song",
        "overall_confidence": 0.5,
        "needs_review": False,
    }
    defaults.update(overrides)
    return Track(**defaults)  # type: ignore[arg-type]


def test_preview_describes_a_legal_move_without_touching_the_filesystem(
    orchestrator: OperationOrchestrator,
    track_repo: TrackRepository,
    zone_library: Library,
) -> None:
    source = Path(zone_library.incoming_path) / "track.flac"
    source.write_bytes(b"audio")
    track = _make_track(zone_library, source)
    track_repo.upsert(track)

    result = orchestrator.preview(
        OperationRequest(
            operation_type=OperationType.FILE_MOVE,
            track_id=track.id,
            target_zone=LibraryZone.STAGING,
        )
    )

    assert result.success is True
    assert result.details["old_zone"] == "incoming"
    assert result.details["new_zone"] == "staging"
    assert source.is_file()  # untouched
    assert track_repo.get_by_id(track.id).zone is LibraryZone.INCOMING  # type: ignore[union-attr]


def test_preview_rejects_illegal_zone_transition(
    orchestrator: OperationOrchestrator,
    track_repo: TrackRepository,
    zone_library: Library,
) -> None:
    source = Path(zone_library.library_path) / "track.flac"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"audio")
    track = _make_track(zone_library, source, zone=LibraryZone.LIBRARY)
    track_repo.upsert(track)

    with pytest.raises(OperationError, match="Illegal zone transition"):
        orchestrator.preview(
            OperationRequest(
                operation_type=OperationType.FILE_MOVE,
                track_id=track.id,
                target_zone=LibraryZone.INCOMING,  # library → incoming is illegal
            )
        )


def test_execute_dry_run_delegates_to_preview(
    orchestrator: OperationOrchestrator,
    track_repo: TrackRepository,
    zone_library: Library,
    job_repo: object,
) -> None:
    from vaultseek.db.repositories.job_repo import JobRepository

    assert isinstance(job_repo, JobRepository)
    source = Path(zone_library.incoming_path) / "track.flac"
    source.write_bytes(b"audio")
    track = _make_track(zone_library, source)
    track_repo.upsert(track)

    result = orchestrator.execute(
        OperationRequest(
            operation_type=OperationType.FILE_MOVE,
            track_id=track.id,
            target_zone=LibraryZone.STAGING,
            dry_run=True,
        )
    )

    assert result.success is True
    assert result.details["dry_run"] is True
    assert job_repo.list_by_status(JobStatus.PENDING) == []


def test_execute_enqueues_an_organize_file_job(
    orchestrator: OperationOrchestrator,
    track_repo: TrackRepository,
    zone_library: Library,
    job_repo: object,
) -> None:
    from vaultseek.db.repositories.job_repo import JobRepository

    assert isinstance(job_repo, JobRepository)
    source = Path(zone_library.incoming_path) / "track.flac"
    source.write_bytes(b"audio")
    track = _make_track(zone_library, source)
    track_repo.upsert(track)

    result = orchestrator.execute(
        OperationRequest(
            operation_type=OperationType.FILE_MOVE,
            track_id=track.id,
            target_zone=LibraryZone.STAGING,
            dry_run=False,
        )
    )

    assert result.success is True
    pending = [
        job
        for job in job_repo.list_by_status(JobStatus.PENDING)
        if job.job_type is JobType.ORGANIZE_FILE
    ]
    assert len(pending) == 1
    assert pending[0].payload["track_id"] == str(track.id)
    assert pending[0].payload["target_zone"] == "staging"


def test_rollback_reverses_a_completed_file_move(
    orchestrator: OperationOrchestrator,
    organizer: OrganizerWorker,
    track_repo: TrackRepository,
    operation_repo: OperationRepository,
    zone_library: Library,
    job_queue: JobQueueService,
    job_repo: object,
) -> None:
    from vaultseek.db.repositories.job_repo import JobRepository
    from vaultseek.models.entities.job import Job

    assert isinstance(job_repo, JobRepository)
    source = Path(zone_library.incoming_path) / "track.flac"
    source.write_bytes(b"audio-bytes")
    track = _make_track(zone_library, source, title="Karma Police", track_number=1)
    track_repo.upsert(track)

    job_id = job_queue.enqueue(
        JobType.ORGANIZE_FILE,
        zone_library.id,
        {"track_id": str(track.id), "target_zone": "staging"},
        now=_NOW,
    )
    job_repo.update_status(job_id, JobStatus.RUNNING)
    job = job_repo.get(job_id)
    assert isinstance(job, Job)
    organizer.execute(job)

    moved = track_repo.get_by_id(track.id)
    assert moved is not None
    assert moved.zone is LibraryZone.STAGING
    assert Path(moved.file_path).is_file()
    assert not source.exists()

    history = operation_repo.list_changes_for_track(track.id)
    assert len(history) == 1
    operation_id = history[0].operation_id

    result = orchestrator.rollback(operation_id, now=_NOW)

    assert result.success is True
    assert result.affected_count == 1
    restored = track_repo.get_by_id(track.id)
    assert restored is not None
    assert restored.zone is LibraryZone.INCOMING
    assert Path(restored.file_path).is_file()
    assert Path(restored.file_path).read_bytes() == b"audio-bytes"
    assert not Path(moved.file_path).exists()

    operation = operation_repo.get(operation_id)
    assert operation is not None
    assert operation.status is OperationStatus.ROLLED_BACK
    snapshot = operation_repo.get_snapshot_for_operation(operation_id)
    assert snapshot is not None
    assert snapshot.restored_at == _NOW


def test_rollback_rejects_already_rolled_back_operation(
    orchestrator: OperationOrchestrator,
    organizer: OrganizerWorker,
    track_repo: TrackRepository,
    operation_repo: OperationRepository,
    zone_library: Library,
    job_queue: JobQueueService,
    job_repo: object,
) -> None:
    from vaultseek.db.repositories.job_repo import JobRepository

    assert isinstance(job_repo, JobRepository)
    source = Path(zone_library.incoming_path) / "track.flac"
    source.write_bytes(b"x")
    track = _make_track(zone_library, source)
    track_repo.upsert(track)
    job_id = job_queue.enqueue(
        JobType.ORGANIZE_FILE,
        zone_library.id,
        {"track_id": str(track.id), "target_zone": "staging"},
        now=_NOW,
    )
    job_repo.update_status(job_id, JobStatus.RUNNING)
    organizer.execute(job_repo.get(job_id))  # type: ignore[arg-type]
    operation_id = operation_repo.list_changes_for_track(track.id)[0].operation_id
    orchestrator.rollback(operation_id, now=_NOW)

    with pytest.raises(RollbackError, match="already rolled back"):
        orchestrator.rollback(operation_id, now=_NOW)


def test_rollback_suffixes_when_original_path_is_occupied(
    orchestrator: OperationOrchestrator,
    organizer: OrganizerWorker,
    track_repo: TrackRepository,
    operation_repo: OperationRepository,
    zone_library: Library,
    job_queue: JobQueueService,
    job_repo: object,
) -> None:
    from vaultseek.db.repositories.job_repo import JobRepository

    assert isinstance(job_repo, JobRepository)
    source = Path(zone_library.incoming_path) / "track.flac"
    source.write_bytes(b"original")
    track = _make_track(zone_library, source)
    track_repo.upsert(track)
    job_id = job_queue.enqueue(
        JobType.ORGANIZE_FILE,
        zone_library.id,
        {"track_id": str(track.id), "target_zone": "staging"},
        now=_NOW,
    )
    job_repo.update_status(job_id, JobStatus.RUNNING)
    organizer.execute(job_repo.get(job_id))  # type: ignore[arg-type]

    # Something else now occupies the original incoming path.
    source.write_bytes(b"occupied")
    operation_id = operation_repo.list_changes_for_track(track.id)[0].operation_id

    result = orchestrator.rollback(operation_id, now=_NOW)

    assert result.success is True
    restored = track_repo.get_by_id(track.id)
    assert restored is not None
    assert restored.zone is LibraryZone.INCOMING
    assert restored.file_path != str(source)
    assert Path(restored.file_path).name == "track (1).flac"
    assert Path(restored.file_path).read_bytes() == b"original"


def test_list_recent_and_history_for_track(
    orchestrator: OperationOrchestrator,
    organizer: OrganizerWorker,
    track_repo: TrackRepository,
    zone_library: Library,
    job_queue: JobQueueService,
    job_repo: object,
) -> None:
    from vaultseek.db.repositories.job_repo import JobRepository

    assert isinstance(job_repo, JobRepository)
    source = Path(zone_library.incoming_path) / "track.flac"
    source.write_bytes(b"x")
    track = _make_track(zone_library, source)
    track_repo.upsert(track)
    job_id = job_queue.enqueue(
        JobType.ORGANIZE_FILE,
        zone_library.id,
        {"track_id": str(track.id), "target_zone": "staging"},
        now=_NOW,
    )
    job_repo.update_status(job_id, JobStatus.RUNNING)
    organizer.execute(job_repo.get(job_id))  # type: ignore[arg-type]

    recent = orchestrator.list_recent(limit=5)
    assert len(recent) >= 1
    assert recent[0].operation_type is OperationType.FILE_MOVE

    history = orchestrator.history_for_track(track.id)
    assert len(history) == 1
    assert history[0].old_zone == "incoming"
    assert history[0].new_zone == "staging"


def test_rollback_unknown_operation_raises(orchestrator: OperationOrchestrator) -> None:
    with pytest.raises(RollbackError, match="not found"):
        orchestrator.rollback(generate_uuid7())
