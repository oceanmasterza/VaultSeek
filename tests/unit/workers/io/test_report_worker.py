"""Unit tests for vaultseek.workers.io.report_worker."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import Engine

from vaultseek.db.repositories.duplicate_repo import DuplicateRepository
from vaultseek.db.repositories.job_repo import JobRepository
from vaultseek.db.repositories.library_repo import LibraryRepository
from vaultseek.db.repositories.review_repo import ReviewRepository
from vaultseek.db.repositories.track_repo import TrackRepository
from vaultseek.db.uuid_utils import generate_uuid7
from vaultseek.models.entities.job import Job, JobStatus, JobType
from vaultseek.models.entities.library import Library
from vaultseek.models.entities.track import LibraryZone, Track
from vaultseek.services.job_queue_service import JobQueueService
from vaultseek.services.report_service import ReportService
from vaultseek.workers.io.report_worker import ReportWorker

_NOW = datetime(2026, 7, 18, tzinfo=UTC)


@pytest.fixture
def library_repo(engine: Engine) -> LibraryRepository:
    return LibraryRepository(engine)


@pytest.fixture
def zone_library(library_repo: LibraryRepository, library_id: UUID, tmp_path: Path) -> Library:
    library = Library(
        id=library_id,
        name="Vault",
        incoming_path=str(tmp_path / "incoming"),
        staging_path=str(tmp_path / "staging"),
        library_path=str(tmp_path / "library"),
        archive_path=str(tmp_path / "archive"),
        created_at=_NOW,
        updated_at=_NOW,
    )
    library_repo.upsert(library)
    return library


@pytest.fixture
def worker(
    library_repo: LibraryRepository,
    track_repo: TrackRepository,
    review_repo: ReviewRepository,
    duplicate_repo: DuplicateRepository,
    job_queue: JobQueueService,
    tmp_path: Path,
) -> ReportWorker:
    service = ReportService(
        library_repo,
        track_repo,
        review_repo,
        duplicate_repo,
        reports_dir=tmp_path / "reports",
        job_queue=job_queue,
    )
    return ReportWorker(service, job_queue)


def test_execute_writes_report_and_completes_job(
    worker: ReportWorker,
    track_repo: TrackRepository,
    zone_library: Library,
    job_queue: JobQueueService,
    job_repo: JobRepository,
    tmp_path: Path,
) -> None:
    track_id = generate_uuid7()
    track_repo.upsert(
        Track(
            id=track_id,
            library_id=zone_library.id,
            zone=LibraryZone.LIBRARY,
            file_path=f"C:/library/{track_id}.flac",
            file_name=f"{track_id}.flac",
            file_size=100,
            file_modified=_NOW,
            created_at=_NOW,
            updated_at=_NOW,
        )
    )
    out = tmp_path / "out.json"
    job_id = job_queue.enqueue(
        JobType.GENERATE_REPORT,
        zone_library.id,
        {"report_type": "library_summary", "format": "json", "output_path": str(out)},
        now=_NOW,
    )
    job_repo.update_status(job_id, JobStatus.RUNNING)
    job = job_repo.get(job_id)
    assert isinstance(job, Job)

    worker.execute(job)

    assert job_repo.get(job_id).status is JobStatus.COMPLETED  # type: ignore[union-attr]
    assert out.is_file()
    assert b"library_summary" in out.read_bytes()


def test_execute_fails_on_invalid_format(
    worker: ReportWorker,
    zone_library: Library,
    job_queue: JobQueueService,
    job_repo: JobRepository,
) -> None:
    job_id = job_queue.enqueue(
        JobType.GENERATE_REPORT,
        zone_library.id,
        {"format": "pdf"},
        now=_NOW,
    )
    job_repo.update_status(job_id, JobStatus.RUNNING)
    job = job_repo.get(job_id)
    assert job is not None

    worker.execute(job)

    updated = job_repo.get(job_id)
    assert updated is not None
    assert updated.status is JobStatus.RETRY
    assert updated.error_message is not None
    assert "Invalid report payload" in updated.error_message
