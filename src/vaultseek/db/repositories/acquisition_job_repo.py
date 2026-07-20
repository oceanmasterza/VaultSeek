"""AcquisitionJobRepository — persistence for the `acquisition_jobs` table."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Engine, Row, select

from vaultseek.db.repositories.base import batch_upsert
from vaultseek.db.tables import acquisition_jobs as acquisition_jobs_table
from vaultseek.db.uuid_utils import blob_to_uuid, uuid_to_blob
from vaultseek.models.entities.acquisition_job import (
    AcquisitionJob,
    AcquisitionJobState,
    AcquisitionJobType,
)


class AcquisitionJobRepository:
    """Reads and writes `AcquisitionJob` entities against `acquisition_jobs`."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def create(self, job: AcquisitionJob) -> None:
        """Persist a single job (insert, or overwrite if its id already exists)."""
        self.batch_create([job])

    def batch_create(self, jobs: Sequence[AcquisitionJob]) -> None:
        """Persist many jobs in one transaction."""
        rows = [_to_row(job) for job in jobs]
        with self._engine.begin() as conn:
            batch_upsert(conn, acquisition_jobs_table, rows, conflict_columns=["id"])

    def get(self, job_id: UUID) -> AcquisitionJob | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                select(acquisition_jobs_table).where(
                    acquisition_jobs_table.c.id == uuid_to_blob(job_id)
                )
            ).first()
        return _from_row(row) if row is not None else None

    def list_by_library(
        self,
        library_id: UUID | None = None,
        *,
        state: AcquisitionJobState | None = None,
    ) -> list[AcquisitionJob]:
        statement = select(acquisition_jobs_table).order_by(
            acquisition_jobs_table.c.priority,
            acquisition_jobs_table.c.created_at,
        )
        if library_id is not None:
            statement = statement.where(
                acquisition_jobs_table.c.library_id == uuid_to_blob(library_id)
            )
        if state is not None:
            statement = statement.where(acquisition_jobs_table.c.state == state.value)

        with self._engine.connect() as conn:
            rows = conn.execute(statement).all()
        return [_from_row(row) for row in rows]


def _to_row(job: AcquisitionJob) -> dict[str, object]:
    return {
        "id": uuid_to_blob(job.id),
        "library_id": uuid_to_blob(job.library_id),
        "job_type": job.job_type.value,
        "state": job.state.value,
        "artist": job.artist,
        "album": job.album,
        "title": job.title,
        "year": job.year,
        "mb_release_id": job.mb_release_id,
        "preferred_codec": job.preferred_codec,
        "preferred_bit_depth": job.preferred_bit_depth,
        "preferred_country": job.preferred_country,
        "preferred_providers": json.dumps(list(job.preferred_providers)),
        "selected_result_id": job.selected_result_id,
        "selected_provider_id": job.selected_provider_id,
        "retry_count": job.retry_count,
        "priority": job.priority,
        "progress": job.progress,
        "error_message": job.error_message,
        "history": json.dumps(list(job.history)),
        "extra": json.dumps(job.extra),
        "created_at": job.created_at.isoformat(),
        "updated_at": job.updated_at.isoformat(),
    }


def _from_row(row: Row[Any]) -> AcquisitionJob:
    history_raw = json.loads(row.history or "[]")
    providers_raw = json.loads(row.preferred_providers or "[]")
    extra_raw = json.loads(row.extra or "{}")
    return AcquisitionJob(
        id=blob_to_uuid(row.id),
        library_id=blob_to_uuid(row.library_id),
        job_type=AcquisitionJobType(row.job_type),
        state=AcquisitionJobState(row.state),
        created_at=datetime.fromisoformat(row.created_at),
        updated_at=datetime.fromisoformat(row.updated_at),
        artist=row.artist,
        album=row.album,
        title=row.title,
        year=row.year,
        mb_release_id=row.mb_release_id,
        preferred_codec=row.preferred_codec,
        preferred_bit_depth=row.preferred_bit_depth,
        preferred_country=row.preferred_country,
        preferred_providers=tuple(str(item) for item in providers_raw),
        selected_result_id=row.selected_result_id,
        selected_provider_id=row.selected_provider_id,
        retry_count=int(row.retry_count),
        priority=int(row.priority),
        progress=float(row.progress),
        error_message=row.error_message,
        history=tuple(str(item) for item in history_raw),
        extra=dict(extra_raw),
    )
