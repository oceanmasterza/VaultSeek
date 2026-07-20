"""Unit tests for vaultseek.services.job_queue_service.JobQueueService."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from vaultseek.core.config import PipelineConfig
from vaultseek.db.repositories.job_repo import JobRepository
from vaultseek.db.uuid_utils import generate_uuid7
from vaultseek.models.entities.job import Job, JobStatus, JobType
from vaultseek.services.dto.job_dto import JobCreate
from vaultseek.services.job_queue_service import JobQueueService

_NOW = datetime(2026, 7, 15, 12, 0, 0, tzinfo=UTC)


def test_enqueue_persists_a_pending_job_with_defaults(
    job_repo: JobRepository, pipeline_config: PipelineConfig, library_id: UUID
) -> None:
    service = JobQueueService(job_repo, pipeline_config)

    job_id = service.enqueue(JobType.SCAN_DIRECTORY, library_id, {"path": "C:/incoming"}, now=_NOW)

    job = job_repo.get(job_id)
    assert job is not None
    assert job.status is JobStatus.PENDING
    assert job.priority == 100
    assert job.created_at == _NOW
    assert job.payload == {"path": "C:/incoming"}


def test_enqueue_uses_real_current_time_when_now_is_not_given(
    job_repo: JobRepository, pipeline_config: PipelineConfig, library_id: UUID
) -> None:
    service = JobQueueService(job_repo, pipeline_config)
    before = datetime.now(UTC)

    job_id = service.enqueue(JobType.SCAN_DIRECTORY, library_id, {})

    job = job_repo.get(job_id)
    assert job is not None
    assert before <= job.created_at <= datetime.now(UTC)


def test_enqueue_batch_persists_every_job_and_returns_their_ids(
    job_repo: JobRepository, pipeline_config: PipelineConfig, library_id: UUID
) -> None:
    service = JobQueueService(job_repo, pipeline_config)
    specs = [
        JobCreate(job_type=JobType.HASH_FILE, library_id=library_id, payload={"n": i})
        for i in range(5)
    ]

    ids = service.enqueue_batch(specs, now=_NOW)

    assert len(ids) == 5
    for job_id in ids:
        job = job_repo.get(job_id)
        assert job is not None
        assert job.status is JobStatus.PENDING


def test_claim_pending_delegates_to_the_repository(
    job_repo: JobRepository, pipeline_config: PipelineConfig, library_id: UUID
) -> None:
    service = JobQueueService(job_repo, pipeline_config)
    job_id = service.enqueue(JobType.HASH_FILE, library_id, {}, now=_NOW)

    claimed = service.claim_pending(JobType.HASH_FILE, now=_NOW)

    assert [job.id for job in claimed] == [job_id]
    assert job_repo.get(job_id).status is JobStatus.RUNNING  # type: ignore[union-attr]


def test_mark_running_sets_status_and_started_at(
    job_repo: JobRepository, pipeline_config: PipelineConfig, library_id: UUID
) -> None:
    service = JobQueueService(job_repo, pipeline_config)
    job_id = service.enqueue(JobType.HASH_FILE, library_id, {}, now=_NOW)

    service.mark_running(job_id, now=_NOW)

    job = job_repo.get(job_id)
    assert job is not None
    assert job.status is JobStatus.RUNNING
    assert job.started_at == _NOW


def test_mark_completed_sets_status_and_completed_at(
    job_repo: JobRepository, pipeline_config: PipelineConfig, library_id: UUID
) -> None:
    service = JobQueueService(job_repo, pipeline_config)
    job_id = service.enqueue(JobType.HASH_FILE, library_id, {}, now=_NOW)

    service.mark_completed(job_id, now=_NOW)

    job = job_repo.get(job_id)
    assert job is not None
    assert job.status is JobStatus.COMPLETED
    assert job.completed_at == _NOW


def test_mark_completed_stores_summary_and_result_payload(
    job_repo: JobRepository, pipeline_config: PipelineConfig, library_id: UUID
) -> None:
    service = JobQueueService(job_repo, pipeline_config)
    job_id = service.enqueue(JobType.FETCH_ARTWORK, library_id, {"track_id": "x"}, now=_NOW)

    service.mark_completed(
        job_id,
        now=_NOW,
        summary="Cover saved (embedded_art, 600x600) for 'a.flac'",
        result={"outcome": "saved", "width": 600},
    )

    job = job_repo.get(job_id)
    assert job is not None
    assert job.status is JobStatus.COMPLETED
    assert job.error_message == "Cover saved (embedded_art, 600x600) for 'a.flac'"
    assert job.payload["outcome"] == "saved"
    assert job.payload["width"] == 600
    assert job.payload["track_id"] == "x"


def test_mark_failed_is_a_noop_for_an_unknown_job(
    job_repo: JobRepository, pipeline_config: PipelineConfig
) -> None:
    service = JobQueueService(job_repo, pipeline_config)

    service.mark_failed(UUID(int=0), "boom", now=_NOW)  # must not raise


def test_mark_failed_schedules_a_backoff_retry_while_attempts_remain(
    job_repo: JobRepository, pipeline_config: PipelineConfig, library_id: UUID
) -> None:
    config = PipelineConfig(retry_base_delay_seconds=10.0, retry_max_delay_seconds=300.0)
    service = JobQueueService(job_repo, config)
    job_id = service.enqueue(JobType.HASH_FILE, library_id, {}, now=_NOW)  # attempt_count=0

    service.mark_failed(job_id, "transient I/O error", now=_NOW)

    job = job_repo.get(job_id)
    assert job is not None
    assert job.status is JobStatus.RETRY
    assert job.attempt_count == 1
    assert job.error_message == "transient I/O error"
    assert job.scheduled_at == _NOW + timedelta(seconds=10.0)  # base * 2**0


def test_mark_failed_marks_permanently_failed_once_attempts_are_exhausted(
    job_repo: JobRepository, pipeline_config: PipelineConfig, library_id: UUID
) -> None:
    service = JobQueueService(job_repo, pipeline_config)
    # attempt_count=2, max_attempts=3 — next_attempt (3) is not < max_attempts,
    # so this single failure must exhaust the job immediately.
    job = Job(
        id=generate_uuid7(),
        library_id=library_id,
        job_type=JobType.HASH_FILE,
        status=JobStatus.RUNNING,
        payload={},
        created_at=_NOW,
        attempt_count=2,
        max_attempts=3,
    )
    job_repo.create(job)

    service.mark_failed(job.id, "final failure", now=_NOW)

    loaded = job_repo.get(job.id)
    assert loaded is not None
    assert loaded.status is JobStatus.FAILED
    assert loaded.attempt_count == 3
    assert loaded.completed_at == _NOW


def test_mark_failed_caps_the_backoff_delay_at_the_configured_maximum(
    job_repo: JobRepository, library_id: UUID
) -> None:
    config = PipelineConfig(retry_base_delay_seconds=10.0, retry_max_delay_seconds=15.0)
    service = JobQueueService(job_repo, config)
    # base * 2**attempt_count = 10 * 2**5 = 320s, far past the 15s cap.
    job = Job(
        id=generate_uuid7(),
        library_id=library_id,
        job_type=JobType.HASH_FILE,
        status=JobStatus.RUNNING,
        payload={},
        created_at=_NOW,
        attempt_count=5,
        max_attempts=10,
    )
    job_repo.create(job)

    service.mark_failed(job.id, "still failing", now=_NOW)

    loaded = job_repo.get(job.id)
    assert loaded is not None
    assert loaded.status is JobStatus.RETRY
    assert loaded.scheduled_at == _NOW + timedelta(seconds=15.0)


def test_cancel_sets_status_and_completed_at(
    job_repo: JobRepository, pipeline_config: PipelineConfig, library_id: UUID
) -> None:
    service = JobQueueService(job_repo, pipeline_config)
    job_id = service.enqueue(JobType.HASH_FILE, library_id, {}, now=_NOW)

    service.cancel(job_id, now=_NOW)

    job = job_repo.get(job_id)
    assert job is not None
    assert job.status is JobStatus.CANCELLED
    assert job.completed_at == _NOW


def test_retry_failed_resets_a_terminal_job_to_pending(
    job_repo: JobRepository, pipeline_config: PipelineConfig, library_id: UUID
) -> None:
    service = JobQueueService(job_repo, pipeline_config)
    job_id = service.enqueue(JobType.HASH_FILE, library_id, {}, now=_NOW)
    job_repo.update_status(
        job_id, JobStatus.FAILED, error_message="dead", attempt_count=3, completed_at=_NOW
    )

    service.retry_failed(job_id)

    job = job_repo.get(job_id)
    assert job is not None
    assert job.status is JobStatus.PENDING
    assert job.attempt_count == 0
    assert job.error_message is None


def test_recover_orphaned_delegates_to_the_repository(
    job_repo: JobRepository, pipeline_config: PipelineConfig, library_id: UUID
) -> None:
    service = JobQueueService(job_repo, pipeline_config)
    job_id = service.enqueue(JobType.HASH_FILE, library_id, {}, now=_NOW)
    job_repo.update_status(job_id, JobStatus.RUNNING)

    count = service.recover_orphaned(now=_NOW)

    assert count == 1
    assert job_repo.get(job_id).status is JobStatus.RETRY  # type: ignore[union-attr]


def test_promote_due_retries_delegates_to_the_repository(
    job_repo: JobRepository, pipeline_config: PipelineConfig, library_id: UUID
) -> None:
    service = JobQueueService(job_repo, pipeline_config)
    job_id = service.enqueue(JobType.HASH_FILE, library_id, {}, now=_NOW)
    job_repo.update_status(job_id, JobStatus.RETRY, scheduled_at=_NOW - timedelta(seconds=1))

    count = service.promote_due_retries(now=_NOW)

    assert count == 1
    assert job_repo.get(job_id).status is JobStatus.PENDING  # type: ignore[union-attr]


def test_get_stats_aggregates_correctly(
    job_repo: JobRepository, pipeline_config: PipelineConfig, library_id: UUID
) -> None:
    service = JobQueueService(job_repo, pipeline_config)
    service.enqueue(JobType.HASH_FILE, library_id, {}, now=_NOW)
    service.enqueue(JobType.HASH_FILE, library_id, {}, now=_NOW)
    running_id = service.enqueue(JobType.SCAN_DIRECTORY, library_id, {}, now=_NOW)
    job_repo.update_status(running_id, JobStatus.RUNNING, started_at=_NOW)
    failed_id = service.enqueue(JobType.HASH_FILE, library_id, {}, now=_NOW)
    job_repo.update_status(failed_id, JobStatus.FAILED, completed_at=_NOW)
    completed_today_id = service.enqueue(JobType.HASH_FILE, library_id, {}, now=_NOW)
    job_repo.update_status(completed_today_id, JobStatus.COMPLETED, completed_at=_NOW)
    completed_yesterday_id = service.enqueue(JobType.HASH_FILE, library_id, {}, now=_NOW)
    job_repo.update_status(
        completed_yesterday_id, JobStatus.COMPLETED, completed_at=_NOW - timedelta(days=1)
    )

    stats = service.get_stats(library_id, now=_NOW)

    assert stats.pending == 2
    assert stats.running == 1
    assert stats.failed == 1
    assert stats.completed_today == 1
    assert stats.by_type == {"hash_file": 2, "scan_directory": 1}
