"""JobQueueService — application-layer orchestration for the job queue.

Wraps :class:`JobRepository` with the operations `JobDispatcher` and a
future Job Monitor GUI actually need (see
docs/architecture/04-service-layer.md, "JobQueueService").

Every write here is a small, single-row job-status transition — they go
straight through `JobRepository`, not `DatabaseWriter`'s batched queue.
`DatabaseWriter`'s single-writer batching exists to solve *high-volume*
writes (thousands of `Track`/`FileIdentity` rows per scan — see
docs/architecture/08-performance.md, "Database Writer Queue"); job
bookkeeping never reaches that volume, so routing it through a
batch-upsert-oriented queue would add complexity without a throughput
payoff. Scanner/Hash workers use `DatabaseWriter` directly for *their*
output rows — see :mod:`vaultseek.workers`.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from vaultseek.core.config import PipelineConfig
from vaultseek.db.repositories.job_repo import JobRepository
from vaultseek.db.uuid_utils import generate_uuid7
from vaultseek.models.entities.job import Job, JobStatus, JobType
from vaultseek.services.dto.job_dto import JobCreate, JobStatsDTO


class JobQueueService:
    def __init__(self, job_repository: JobRepository, pipeline_config: PipelineConfig) -> None:
        self._jobs = job_repository
        self._config = pipeline_config

    def enqueue(
        self,
        job_type: JobType,
        library_id: UUID,
        payload: dict[str, Any],
        *,
        priority: int = 100,
        parent_job_id: UUID | None = None,
        now: datetime | None = None,
    ) -> UUID:
        job = Job(
            id=generate_uuid7(),
            library_id=library_id,
            job_type=job_type,
            status=JobStatus.PENDING,
            payload=payload,
            created_at=_resolve_now(now),
            priority=priority,
            parent_job_id=parent_job_id,
        )
        self._jobs.create(job)
        return job.id

    def enqueue_batch(
        self, jobs: Sequence[JobCreate], *, now: datetime | None = None
    ) -> list[UUID]:
        created_at = _resolve_now(now)
        built = [
            Job(
                id=generate_uuid7(),
                library_id=spec.library_id,
                job_type=spec.job_type,
                status=JobStatus.PENDING,
                payload=spec.payload,
                created_at=created_at,
                priority=spec.priority,
                parent_job_id=spec.parent_job_id,
            )
            for spec in jobs
        ]
        self._jobs.batch_create(built)
        return [job.id for job in built]

    def claim_pending(
        self, job_type: JobType, limit: int = 10, *, now: datetime | None = None
    ) -> Sequence[Job]:
        return self._jobs.claim_pending(job_type, limit=limit, now=_resolve_now(now))

    def mark_running(self, job_id: UUID, *, now: datetime | None = None) -> None:
        self._jobs.update_status(job_id, JobStatus.RUNNING, started_at=_resolve_now(now))

    def mark_completed(
        self,
        job_id: UUID,
        *,
        now: datetime | None = None,
        summary: str | None = None,
        result: dict[str, Any] | None = None,
    ) -> None:
        if result:
            self._jobs.merge_payload(job_id, result)
        self._jobs.update_status(
            job_id,
            JobStatus.COMPLETED,
            completed_at=_resolve_now(now),
            error_message=summary,
        )

    def has_active_for_track(
        self,
        job_type: JobType,
        library_id: UUID,
        track_id: UUID,
    ) -> bool:
        """True when a pending/running/retry job of this type already targets the track."""
        return self._jobs.has_active_for_track(library_id, job_type, track_id)

    def mark_failed(
        self, job_id: UUID, error: str, *, now: datetime | None = None, terminal: bool = False
    ) -> None:
        """Record a worker failure. Schedules another attempt with
        exponential backoff (`delay = retry_base_delay_seconds *
        2**attempt_count`, capped at `retry_max_delay_seconds` — see
        `PipelineConfig`) while attempts remain, otherwise marks the job
        permanently `failed`. Distinct from :meth:`retry_failed`, which is
        a *manual* re-queue of an already-terminal job.

        Pass ``terminal=True`` for non-retryable errors (missing file after
        a move, etc.) so watch/scan storms do not burn three attempts each.
        """
        job = self._jobs.get(job_id)
        if job is None:
            return

        current_time = _resolve_now(now)
        next_attempt = job.attempt_count + 1
        if (not terminal) and next_attempt < job.max_attempts:
            delay_seconds = min(
                self._config.retry_base_delay_seconds * (2**job.attempt_count),
                self._config.retry_max_delay_seconds,
            )
            self._jobs.update_status(
                job_id,
                JobStatus.RETRY,
                error_message=error,
                attempt_count=next_attempt,
                scheduled_at=current_time + timedelta(seconds=delay_seconds),
            )
        else:
            self._jobs.update_status(
                job_id,
                JobStatus.FAILED,
                error_message=error,
                attempt_count=next_attempt,
                completed_at=current_time,
            )

    def cancel(self, job_id: UUID, *, now: datetime | None = None) -> None:
        self._jobs.update_status(job_id, JobStatus.CANCELLED, completed_at=_resolve_now(now))

    def retry_failed(self, job_id: UUID) -> None:
        """Manually re-queue an already-`failed` job with a clean slate
        (e.g. a user clicking "Retry" in the Job Monitor)."""
        self._jobs.reset_for_retry(job_id)

    def recover_orphaned(self, *, now: datetime | None = None) -> int:
        """Reset every `running` job back to `retry` — call once at
        startup, before any dispatcher starts polling. See
        docs/architecture/10-revision-v2.md, "Resume After Crash."
        """
        return self._jobs.recover_orphaned(now=_resolve_now(now))

    def promote_due_retries(self, *, now: datetime | None = None) -> int:
        """Move every `retry` job whose backoff has elapsed back to
        `pending`. Call this each dispatcher poll cycle, before
        :meth:`claim_pending`."""
        return self._jobs.promote_due_retries(now=_resolve_now(now))

    def get_stats(self, library_id: UUID, *, now: datetime | None = None) -> JobStatsDTO:
        current_time = _resolve_now(now)
        start_of_today = current_time.replace(hour=0, minute=0, second=0, microsecond=0)

        by_status = self._jobs.count_by_status(library_id)
        by_type = self._jobs.count_by_type(
            library_id, statuses=(JobStatus.PENDING, JobStatus.RUNNING)
        )
        completed_today = self._jobs.count_completed_since(library_id, since=start_of_today)

        return JobStatsDTO(
            pending=by_status.get(JobStatus.PENDING.value, 0),
            running=by_status.get(JobStatus.RUNNING.value, 0),
            failed=by_status.get(JobStatus.FAILED.value, 0),
            completed_today=completed_today,
            by_type=by_type,
        )


def _resolve_now(now: datetime | None) -> datetime:
    return now if now is not None else datetime.now(UTC)
