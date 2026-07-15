"""Unit tests for musicvault.db.repositories.job_repo.JobRepository."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Engine

from musicvault.db.repositories.job_repo import JobRepository
from musicvault.db.uuid_utils import generate_uuid7
from musicvault.models.entities.job import Job, JobStatus, JobType

_NOW = datetime(2026, 7, 15, tzinfo=UTC)


def _make_job(library_id: UUID, **overrides: object) -> Job:
    defaults: dict[str, object] = {
        "id": generate_uuid7(),
        "library_id": library_id,
        "job_type": JobType.SCAN_DIRECTORY,
        "status": JobStatus.PENDING,
        "payload": {"path": "C:/incoming"},
        "created_at": _NOW,
    }
    defaults.update(overrides)
    return Job(**defaults)  # type: ignore[arg-type]


def test_create_and_get_round_trips_every_field(engine: Engine, library_id: UUID) -> None:
    repo = JobRepository(engine)
    parent_job = _make_job(library_id)
    repo.create(parent_job)

    job = _make_job(
        library_id,
        priority=50,
        parent_job_id=parent_job.id,
        attempt_count=1,
        max_attempts=5,
        error_message="transient failure",
        started_at=_NOW,
        completed_at=_NOW,
        scheduled_at=_NOW,
    )

    repo.create(job)
    loaded = repo.get(job.id)

    assert loaded == job


def test_get_returns_none_for_missing_job(engine: Engine) -> None:
    repo = JobRepository(engine)

    assert repo.get(generate_uuid7()) is None


def test_batch_create_persists_multiple_jobs(engine: Engine, library_id: UUID) -> None:
    repo = JobRepository(engine)
    batch = [_make_job(library_id) for _ in range(10)]

    repo.batch_create(batch)

    loaded_ids = {loaded.id for job in batch if (loaded := repo.get(job.id)) is not None}
    assert loaded_ids == {job.id for job in batch}


def test_list_by_status_filters_correctly(engine: Engine, library_id: UUID) -> None:
    repo = JobRepository(engine)
    pending = _make_job(library_id, status=JobStatus.PENDING)
    completed = _make_job(library_id, status=JobStatus.COMPLETED)
    repo.create(pending)
    repo.create(completed)

    results = repo.list_by_status(JobStatus.PENDING)

    assert {job.id for job in results} == {pending.id}


def test_list_by_status_filters_by_library_when_given(engine: Engine, library_id: UUID) -> None:
    repo = JobRepository(engine)
    job = _make_job(library_id, status=JobStatus.PENDING)
    repo.create(job)

    same_library_results = repo.list_by_status(JobStatus.PENDING, library_id=library_id)
    other_library_results = repo.list_by_status(JobStatus.PENDING, library_id=generate_uuid7())

    assert {j.id for j in same_library_results} == {job.id}
    assert other_library_results == []


def test_update_status_changes_status_and_error_message(engine: Engine, library_id: UUID) -> None:
    repo = JobRepository(engine)
    job = _make_job(library_id, status=JobStatus.RUNNING)
    repo.create(job)

    repo.update_status(job.id, JobStatus.FAILED, error_message="disk full", completed_at=_NOW)

    loaded = repo.get(job.id)
    assert loaded is not None
    assert loaded.status is JobStatus.FAILED
    assert loaded.error_message == "disk full"
    assert loaded.completed_at == _NOW
