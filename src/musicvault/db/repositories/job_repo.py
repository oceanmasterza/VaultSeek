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

from sqlalchemy import Engine, Row, select, update

from musicvault.db.repositories.base import batch_upsert
from musicvault.db.tables import jobs as jobs_table
from musicvault.db.uuid_utils import blob_to_uuid, uuid_to_blob
from musicvault.models.entities.job import Job, JobStatus, JobType


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

    def list_by_status(self, status: JobStatus, *, library_id: UUID | None = None) -> list[Job]:
        statement = select(jobs_table).where(jobs_table.c.status == status.value)
        if library_id is not None:
            statement = statement.where(jobs_table.c.library_id == uuid_to_blob(library_id))

        with self._engine.connect() as conn:
            rows = conn.execute(statement).all()
        return [_from_row(row) for row in rows]

    def update_status(
        self,
        job_id: UUID,
        status: JobStatus,
        *,
        error_message: str | None = None,
        completed_at: datetime | None = None,
    ) -> None:
        values: dict[str, object] = {"status": status.value}
        if error_message is not None:
            values["error_message"] = error_message
        if completed_at is not None:
            values["completed_at"] = completed_at.isoformat()

        with self._engine.begin() as conn:
            conn.execute(
                update(jobs_table).where(jobs_table.c.id == uuid_to_blob(job_id)).values(**values)
            )


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
