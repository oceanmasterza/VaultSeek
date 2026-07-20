"""AcquisitionEngine — coordinates AcquisitionJob lifecycle (skeleton)."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

from vaultseek.db.uuid_utils import generate_uuid7
from vaultseek.models.entities.acquisition_job import (
    AcquisitionJob,
    AcquisitionJobState,
    AcquisitionJobType,
    validate_transition,
)
from vaultseek.services.provider_manager import ProviderManager


class AcquisitionEngine:
    """In-memory AcquisitionJob coordinator (persistence arrives later)."""

    def __init__(self, provider_manager: ProviderManager) -> None:
        self._providers = provider_manager
        self._jobs: dict[UUID, AcquisitionJob] = {}

    def create_job(
        self,
        *,
        library_id: UUID,
        job_type: AcquisitionJobType,
        artist: str | None = None,
        album: str | None = None,
        title: str | None = None,
        year: int | None = None,
        mb_release_id: str | None = None,
        preferred_codec: str | None = None,
        priority: int = 100,
    ) -> AcquisitionJob:
        now = datetime.now(UTC)
        job = AcquisitionJob(
            id=generate_uuid7(),
            library_id=library_id,
            job_type=job_type,
            state=AcquisitionJobState.CREATED,
            created_at=now,
            updated_at=now,
            artist=artist,
            album=album,
            title=title,
            year=year,
            mb_release_id=mb_release_id,
            preferred_codec=preferred_codec,
            priority=priority,
            history=(f"{now.isoformat()} created",),
        )
        self._jobs[job.id] = job
        return job

    def get(self, job_id: UUID) -> AcquisitionJob | None:
        return self._jobs.get(job_id)

    def list_jobs(self, *, library_id: UUID | None = None) -> list[AcquisitionJob]:
        jobs = list(self._jobs.values())
        if library_id is not None:
            jobs = [job for job in jobs if job.library_id == library_id]
        return sorted(jobs, key=lambda j: j.priority)

    def queue(self, job_id: UUID) -> AcquisitionJob:
        return self._transition(job_id, AcquisitionJobState.QUEUED)

    def cancel(self, job_id: UUID) -> AcquisitionJob:
        return self._transition(job_id, AcquisitionJobState.CANCELLED)

    def advance(self, job_id: UUID, target: AcquisitionJobState, *, note: str = "") -> AcquisitionJob:
        return self._transition(job_id, target, note=note)

    def _transition(
        self,
        job_id: UUID,
        target: AcquisitionJobState,
        *,
        note: str = "",
    ) -> AcquisitionJob:
        job = self._jobs.get(job_id)
        if job is None:
            raise KeyError(f"AcquisitionJob {job_id} not found")
        validate_transition(job.state, target)
        now = datetime.now(UTC)
        entry = f"{now.isoformat()} {job.state.value} -> {target.value}"
        if note:
            entry = f"{entry}: {note}"
        updated = replace(
            job,
            state=target,
            updated_at=now,
            history=job.history + (entry,),
        )
        self._jobs[job_id] = updated
        return updated
