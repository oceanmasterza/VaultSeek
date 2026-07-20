"""Unit tests for WatchFolderService."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import Engine

from vaultseek.db.repositories.job_repo import JobRepository
from vaultseek.db.repositories.library_repo import LibraryRepository
from vaultseek.db.uuid_utils import generate_uuid7
from vaultseek.models.entities.job import JobStatus, JobType
from vaultseek.models.entities.library import Library
from vaultseek.services.job_queue_service import JobQueueService
from vaultseek.services.watch_folder_service import WatchFolderService

_NOW = datetime(2026, 7, 17, tzinfo=UTC)


@pytest.fixture
def library_repo(engine: Engine) -> LibraryRepository:
    return LibraryRepository(engine)


@pytest.fixture
def service(library_repo: LibraryRepository, job_queue: JobQueueService) -> WatchFolderService:
    return WatchFolderService(library_repo, job_queue, poll_interval_seconds=0.05)


def _library(*, watch_enabled: bool) -> Library:
    unique = generate_uuid7()
    return Library(
        id=unique,
        name=f"lib-{unique}",
        incoming_path=f"C:/vault/{unique}/Incoming",
        staging_path=f"C:/vault/{unique}/Staging",
        library_path=f"C:/vault/{unique}/Music",
        archive_path=f"C:/vault/{unique}/Archive",
        created_at=_NOW,
        updated_at=_NOW,
        watch_enabled=watch_enabled,
    )


def _pending_scans(job_repo: JobRepository, library_id: UUID) -> list[dict[str, object]]:
    return [
        job.payload
        for job in job_repo.list_by_status(JobStatus.PENDING, library_id=library_id)
        if job.job_type is JobType.SCAN_DIRECTORY
    ]


def test_poll_once_enqueues_a_priority_scan_for_watched_libraries(
    service: WatchFolderService,
    library_repo: LibraryRepository,
    job_repo: JobRepository,
) -> None:
    watched = _library(watch_enabled=True)
    library_repo.upsert(watched)

    assert service.poll_once(now=_NOW) == 1

    jobs = [
        job
        for job in job_repo.list_by_status(JobStatus.PENDING, library_id=watched.id)
        if job.job_type is JobType.SCAN_DIRECTORY
    ]
    assert len(jobs) == 1
    assert jobs[0].payload == {"directory": watched.incoming_path, "zone": "incoming"}
    assert jobs[0].priority == 50


def test_poll_once_ignores_unwatched_libraries(
    service: WatchFolderService,
    library_repo: LibraryRepository,
    job_repo: JobRepository,
) -> None:
    unwatched = _library(watch_enabled=False)
    library_repo.upsert(unwatched)

    assert service.poll_once(now=_NOW) == 0
    assert _pending_scans(job_repo, unwatched.id) == []


def test_poll_once_skips_a_library_with_an_active_scan(
    service: WatchFolderService,
    library_repo: LibraryRepository,
    job_repo: JobRepository,
) -> None:
    watched = _library(watch_enabled=True)
    library_repo.upsert(watched)

    assert service.poll_once(now=_NOW) == 1
    assert service.poll_once(now=_NOW) == 0

    assert len(_pending_scans(job_repo, watched.id)) == 1


def test_start_and_stop_run_the_polling_thread(
    service: WatchFolderService,
    library_repo: LibraryRepository,
    job_repo: JobRepository,
) -> None:
    watched = _library(watch_enabled=True)
    library_repo.upsert(watched)

    service.start()
    try:
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if _pending_scans(job_repo, watched.id):
                break
            time.sleep(0.02)
    finally:
        service.stop()

    assert len(_pending_scans(job_repo, watched.id)) == 1


def test_start_is_idempotent_and_stop_without_start_is_safe(
    service: WatchFolderService,
) -> None:
    service.stop()
    service.start()
    service.start()
    service.stop()
