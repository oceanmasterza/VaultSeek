"""Unit tests for vaultseek.db.repositories.job_repo.JobRepository."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import Engine

from vaultseek.db.repositories.job_repo import JobRepository
from vaultseek.db.uuid_utils import generate_uuid7
from vaultseek.models.entities.job import Job, JobStatus, JobType

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


def test_update_status_can_set_scheduled_at_and_attempt_count(
    engine: Engine, library_id: UUID
) -> None:
    repo = JobRepository(engine)
    job = _make_job(library_id, status=JobStatus.RUNNING, attempt_count=0)
    repo.create(job)

    retry_at = _NOW + timedelta(seconds=5)
    repo.update_status(job.id, JobStatus.RETRY, scheduled_at=retry_at, attempt_count=1)

    loaded = repo.get(job.id)
    assert loaded is not None
    assert loaded.status is JobStatus.RETRY
    assert loaded.scheduled_at == retry_at
    assert loaded.attempt_count == 1


def test_update_status_can_set_started_at(engine: Engine, library_id: UUID) -> None:
    repo = JobRepository(engine)
    job = _make_job(library_id, status=JobStatus.PENDING, started_at=None)
    repo.create(job)

    repo.update_status(job.id, JobStatus.RUNNING, started_at=_NOW)

    loaded = repo.get(job.id)
    assert loaded is not None
    assert loaded.started_at == _NOW


def test_claim_pending_transitions_matching_jobs_to_running(
    engine: Engine, library_id: UUID
) -> None:
    repo = JobRepository(engine)
    job = _make_job(library_id, job_type=JobType.HASH_FILE, status=JobStatus.PENDING)
    repo.create(job)

    claimed = repo.claim_pending(JobType.HASH_FILE, limit=10, now=_NOW)

    assert [j.id for j in claimed] == [job.id]
    assert claimed[0].status is JobStatus.RUNNING
    assert claimed[0].started_at == _NOW
    loaded = repo.get(job.id)
    assert loaded is not None
    assert loaded.status is JobStatus.RUNNING


def test_claim_pending_ignores_other_job_types_and_statuses(
    engine: Engine, library_id: UUID
) -> None:
    repo = JobRepository(engine)
    repo.create(_make_job(library_id, job_type=JobType.SCAN_DIRECTORY, status=JobStatus.PENDING))
    repo.create(_make_job(library_id, job_type=JobType.HASH_FILE, status=JobStatus.RUNNING))
    repo.create(_make_job(library_id, job_type=JobType.HASH_FILE, status=JobStatus.COMPLETED))

    claimed = repo.claim_pending(JobType.HASH_FILE, limit=10, now=_NOW)

    assert claimed == []


def test_claim_pending_respects_limit_priority_and_age_ordering(
    engine: Engine, library_id: UUID
) -> None:
    repo = JobRepository(engine)
    urgent = _make_job(
        library_id, job_type=JobType.HASH_FILE, priority=1, created_at=_NOW + timedelta(seconds=1)
    )
    older_low_priority = _make_job(
        library_id, job_type=JobType.HASH_FILE, priority=100, created_at=_NOW
    )
    newer_low_priority = _make_job(
        library_id, job_type=JobType.HASH_FILE, priority=100, created_at=_NOW + timedelta(seconds=2)
    )
    for job in (newer_low_priority, older_low_priority, urgent):
        repo.create(job)

    claimed = repo.claim_pending(JobType.HASH_FILE, limit=2, now=_NOW)

    assert [j.id for j in claimed] == [urgent.id, older_low_priority.id]


def test_claim_pending_returns_empty_list_when_nothing_matches(engine: Engine) -> None:
    repo = JobRepository(engine)

    assert repo.claim_pending(JobType.HASH_FILE, limit=10, now=_NOW) == []


def test_recover_orphaned_resets_running_jobs_to_retry(engine: Engine, library_id: UUID) -> None:
    repo = JobRepository(engine)
    running = _make_job(library_id, status=JobStatus.RUNNING)
    pending = _make_job(library_id, status=JobStatus.PENDING)
    repo.create(running)
    repo.create(pending)

    count = repo.recover_orphaned(now=_NOW)

    assert count == 1
    recovered = repo.get(running.id)
    assert recovered is not None
    assert recovered.status is JobStatus.RETRY
    assert recovered.scheduled_at is None
    assert repo.get(pending.id) is not None
    assert repo.get(pending.id).status is JobStatus.PENDING  # type: ignore[union-attr]


def test_recover_orphaned_returns_zero_when_nothing_is_running(engine: Engine) -> None:
    repo = JobRepository(engine)

    assert repo.recover_orphaned(now=_NOW) == 0


def test_promote_due_retries_moves_elapsed_backoff_jobs_to_pending(
    engine: Engine, library_id: UUID
) -> None:
    repo = JobRepository(engine)
    due = _make_job(library_id, status=JobStatus.RETRY, scheduled_at=_NOW - timedelta(seconds=1))
    not_due = _make_job(
        library_id, status=JobStatus.RETRY, scheduled_at=_NOW + timedelta(seconds=60)
    )
    unscheduled = _make_job(library_id, status=JobStatus.RETRY, scheduled_at=None)
    for job in (due, not_due, unscheduled):
        repo.create(job)

    count = repo.promote_due_retries(now=_NOW)

    assert count == 2
    assert repo.get(due.id).status is JobStatus.PENDING  # type: ignore[union-attr]
    assert repo.get(unscheduled.id).status is JobStatus.PENDING  # type: ignore[union-attr]
    assert repo.get(not_due.id).status is JobStatus.RETRY  # type: ignore[union-attr]


def test_promote_due_retries_returns_zero_when_nothing_is_due(engine: Engine) -> None:
    repo = JobRepository(engine)

    assert repo.promote_due_retries(now=_NOW) == 0


def test_reset_for_retry_clears_error_and_reschedules_as_pending(
    engine: Engine, library_id: UUID
) -> None:
    repo = JobRepository(engine)
    job = _make_job(
        library_id,
        status=JobStatus.FAILED,
        attempt_count=3,
        error_message="disk full",
        scheduled_at=_NOW,
        started_at=_NOW,
        completed_at=_NOW,
    )
    repo.create(job)

    repo.reset_for_retry(job.id)

    loaded = repo.get(job.id)
    assert loaded is not None
    assert loaded.status is JobStatus.PENDING
    assert loaded.attempt_count == 0
    assert loaded.error_message is None
    assert loaded.scheduled_at is None
    assert loaded.started_at is None
    assert loaded.completed_at is None


def test_count_by_status_groups_correctly(engine: Engine, library_id: UUID) -> None:
    repo = JobRepository(engine)
    repo.create(_make_job(library_id, status=JobStatus.PENDING))
    repo.create(_make_job(library_id, status=JobStatus.PENDING))
    repo.create(_make_job(library_id, status=JobStatus.RUNNING))

    counts = repo.count_by_status(library_id)

    assert counts == {"pending": 2, "running": 1}


def test_count_by_status_only_counts_the_given_library(engine: Engine, library_id: UUID) -> None:
    repo = JobRepository(engine)
    repo.create(_make_job(library_id, status=JobStatus.PENDING))

    counts = repo.count_by_status(generate_uuid7())

    assert counts == {}


def test_count_by_type_filters_by_status_and_groups_by_type(
    engine: Engine, library_id: UUID
) -> None:
    repo = JobRepository(engine)
    repo.create(_make_job(library_id, job_type=JobType.HASH_FILE, status=JobStatus.PENDING))
    repo.create(_make_job(library_id, job_type=JobType.HASH_FILE, status=JobStatus.RUNNING))
    repo.create(_make_job(library_id, job_type=JobType.SCAN_DIRECTORY, status=JobStatus.COMPLETED))

    counts = repo.count_by_type(library_id, statuses=[JobStatus.PENDING, JobStatus.RUNNING])

    assert counts == {"hash_file": 2}


def test_count_completed_since_filters_by_completion_time(engine: Engine, library_id: UUID) -> None:
    repo = JobRepository(engine)
    repo.create(_make_job(library_id, status=JobStatus.COMPLETED, completed_at=_NOW))
    repo.create(
        _make_job(library_id, status=JobStatus.COMPLETED, completed_at=_NOW - timedelta(days=1))
    )

    count = repo.count_completed_since(library_id, since=_NOW - timedelta(hours=1))

    assert count == 1
