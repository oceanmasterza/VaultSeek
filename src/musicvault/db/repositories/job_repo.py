"""JobRepository — persistence for the `jobs` table.

Converts between :class:`~musicvault.models.entities.job.Job` (the
domain-facing, typed entity) and the raw row shape SQLite actually
stores: UUIDs as 16-byte blobs, timestamps as ISO 8601 text, and the
JSON payload as a serialized string. See
:mod:`musicvault.db.uuid_utils` and the module docstring in
:mod:`musicvault.db.tables` for the conventions this follows.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Engine, Row, func, select, update

from musicvault.db.repositories.base import batch_upsert
from musicvault.db.tables import jobs as jobs_table
from musicvault.db.uuid_utils import blob_to_uuid, uuid_to_blob
from musicvault.models.entities.job import Job, JobStatus, JobType

_CLAIM_ORDER = (jobs_table.c.priority, jobs_table.c.created_at)
"""Matches the `idx_jobs_claim` index (status, job_type, priority,
created_at) — see docs/architecture/10-revision-v2.md, "Claim
semantics." Lower `priority` value claims first."""


class JobRepository:
    """Reads and writes `Job` entities against the `jobs` table."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def create(self, job: Job) -> None:
        """Persist a single job (insert, or overwrite if its id already exists)."""
        self.batch_create([job])

    def batch_create(self, jobs: Sequence[Job]) -> None:
        """Persist many jobs in one transaction — see
        :func:`musicvault.db.repositories.base.batch_upsert`."""
        rows = [_to_row(job) for job in jobs]
        with self._engine.begin() as conn:
            batch_upsert(conn, jobs_table, rows, conflict_columns=["id"])

    def get(self, job_id: UUID) -> Job | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                select(jobs_table).where(jobs_table.c.id == uuid_to_blob(job_id))
            ).first()
        return _from_row(row) if row is not None else None

    def list_by_status(
        self,
        status: JobStatus,
        *,
        library_id: UUID | None = None,
        limit: int | None = None,
    ) -> list[Job]:
        statement = select(jobs_table).where(jobs_table.c.status == status.value)
        if library_id is not None:
            statement = statement.where(jobs_table.c.library_id == uuid_to_blob(library_id))
        statement = statement.order_by(jobs_table.c.created_at.desc())
        if limit is not None:
            statement = statement.limit(limit)

        with self._engine.connect() as conn:
            rows = conn.execute(statement).all()
        return [_from_row(row) for row in rows]

    def update_status(
        self,
        job_id: UUID,
        status: JobStatus,
        *,
        error_message: str | None = None,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
        scheduled_at: datetime | None = None,
        attempt_count: int | None = None,
    ) -> None:
        values: dict[str, object] = {"status": status.value}
        if error_message is not None:
            values["error_message"] = error_message
        if started_at is not None:
            values["started_at"] = started_at.isoformat()
        if completed_at is not None:
            values["completed_at"] = completed_at.isoformat()
        if scheduled_at is not None:
            values["scheduled_at"] = scheduled_at.isoformat()
        if attempt_count is not None:
            values["attempt_count"] = attempt_count

        with self._engine.begin() as conn:
            conn.execute(
                update(jobs_table).where(jobs_table.c.id == uuid_to_blob(job_id)).values(**values)
            )

    def claim_pending(self, job_type: JobType, *, limit: int, now: datetime) -> list[Job]:
        """Atomically transition up to ``limit`` oldest, highest-priority
        `pending` jobs of `job_type` to `running` and return them.

        Claiming (the `SELECT ids` + `UPDATE ... WHERE id IN (ids)`, both
        inside one transaction) rather than a single blind
        ``UPDATE ... LIMIT`` is what makes this safe if `claim_pending` is
        ever called from more than one thread — see
        docs/architecture/10-revision-v2.md, "Claim semantics."
        """
        with self._engine.begin() as conn:
            candidate_ids = (
                conn.execute(
                    select(jobs_table.c.id)
                    .where(
                        jobs_table.c.job_type == job_type.value,
                        jobs_table.c.status == JobStatus.PENDING.value,
                    )
                    .order_by(*_CLAIM_ORDER)
                    .limit(limit)
                )
                .scalars()
                .all()
            )
            if not candidate_ids:
                return []

            conn.execute(
                update(jobs_table)
                .where(jobs_table.c.id.in_(candidate_ids))
                .values(status=JobStatus.RUNNING.value, started_at=now.isoformat())
            )
            claimed_rows = conn.execute(
                select(jobs_table).where(jobs_table.c.id.in_(candidate_ids))
            ).all()

        return [_from_row(row) for row in claimed_rows]

    def recover_orphaned(self, *, now: datetime) -> int:
        """Reset every `running` job back to `retry`, immediately eligible
        (`scheduled_at` unset). Called once at startup: a `running` job
        found on startup can only mean the previous process crashed or was
        killed mid-execution — see docs/architecture/10-revision-v2.md,
        "Resume After Crash."
        """
        with self._engine.begin() as conn:
            orphaned_ids = (
                conn.execute(
                    select(jobs_table.c.id).where(jobs_table.c.status == JobStatus.RUNNING.value)
                )
                .scalars()
                .all()
            )
            if not orphaned_ids:
                return 0

            conn.execute(
                update(jobs_table)
                .where(jobs_table.c.id.in_(orphaned_ids))
                .values(status=JobStatus.RETRY.value, scheduled_at=None)
            )
        return len(orphaned_ids)

    def reset_for_retry(self, job_id: UUID) -> None:
        """Unconditionally reset a job back to `pending` with a clean
        slate (attempt_count=0, error/scheduling fields cleared) — for a
        user manually re-queueing an already-`failed` (terminal) job.

        A dedicated method rather than another `update_status` call
        because that method's `None`-means-"leave unchanged" convention
        cannot express "clear this field back to NULL".
        """
        with self._engine.begin() as conn:
            conn.execute(
                update(jobs_table)
                .where(jobs_table.c.id == uuid_to_blob(job_id))
                .values(
                    status=JobStatus.PENDING.value,
                    attempt_count=0,
                    error_message=None,
                    scheduled_at=None,
                    started_at=None,
                    completed_at=None,
                )
            )

    def promote_due_retries(self, *, now: datetime) -> int:
        """Move every `retry` job whose backoff has elapsed back to
        `pending`, so :meth:`claim_pending` picks it up on its next poll.
        """
        with self._engine.begin() as conn:
            due_ids = (
                conn.execute(
                    select(jobs_table.c.id).where(
                        jobs_table.c.status == JobStatus.RETRY.value,
                        (jobs_table.c.scheduled_at.is_(None))
                        | (jobs_table.c.scheduled_at <= now.isoformat()),
                    )
                )
                .scalars()
                .all()
            )
            if not due_ids:
                return 0

            conn.execute(
                update(jobs_table)
                .where(jobs_table.c.id.in_(due_ids))
                .values(status=JobStatus.PENDING.value)
            )
        return len(due_ids)

    def count_by_status(self, library_id: UUID) -> dict[str, int]:
        """Job counts for `library_id`, grouped by status — the raw
        aggregate :class:`~musicvault.services.dto.job_dto.JobStatsDTO`
        (services layer, which this layer cannot import — see
        "DB layer stays below services" in pyproject.toml) is built from.
        """
        with self._engine.connect() as conn:
            rows = conn.execute(
                select(jobs_table.c.status, func.count())
                .where(jobs_table.c.library_id == uuid_to_blob(library_id))
                .group_by(jobs_table.c.status)
            ).all()
        return {row[0]: row[1] for row in rows}

    def count_by_type(self, library_id: UUID, *, statuses: Sequence[JobStatus]) -> dict[str, int]:
        """Job counts for `library_id` restricted to `statuses`, grouped by job_type."""
        with self._engine.connect() as conn:
            rows = conn.execute(
                select(jobs_table.c.job_type, func.count())
                .where(
                    jobs_table.c.library_id == uuid_to_blob(library_id),
                    jobs_table.c.status.in_([status.value for status in statuses]),
                )
                .group_by(jobs_table.c.job_type)
            ).all()
        return {row[0]: row[1] for row in rows}

    def count_completed_since(self, library_id: UUID, *, since: datetime) -> int:
        with self._engine.connect() as conn:
            return conn.execute(
                select(func.count())
                .select_from(jobs_table)
                .where(
                    jobs_table.c.library_id == uuid_to_blob(library_id),
                    jobs_table.c.status == JobStatus.COMPLETED.value,
                    jobs_table.c.completed_at >= since.isoformat(),
                )
            ).scalar_one()


def _to_row(job: Job) -> dict[str, object]:
    return {
        "id": uuid_to_blob(job.id),
        "library_id": uuid_to_blob(job.library_id),
        "job_type": job.job_type.value,
        "status": job.status.value,
        "priority": job.priority,
        "payload": json.dumps(job.payload),
        "parent_job_id": uuid_to_blob(job.parent_job_id) if job.parent_job_id else None,
        "attempt_count": job.attempt_count,
        "max_attempts": job.max_attempts,
        "error_message": job.error_message,
        "created_at": job.created_at.isoformat(),
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "scheduled_at": job.scheduled_at.isoformat() if job.scheduled_at else None,
    }


def _from_row(row: Row[Any]) -> Job:
    return Job(
        id=blob_to_uuid(row.id),
        library_id=blob_to_uuid(row.library_id),
        job_type=JobType(row.job_type),
        status=JobStatus(row.status),
        payload=json.loads(row.payload),
        created_at=datetime.fromisoformat(row.created_at),
        priority=row.priority,
        parent_job_id=blob_to_uuid(row.parent_job_id) if row.parent_job_id else None,
        attempt_count=row.attempt_count,
        max_attempts=row.max_attempts,
        error_message=row.error_message,
        started_at=datetime.fromisoformat(row.started_at) if row.started_at else None,
        completed_at=datetime.fromisoformat(row.completed_at) if row.completed_at else None,
        scheduled_at=datetime.fromisoformat(row.scheduled_at) if row.scheduled_at else None,
    )
