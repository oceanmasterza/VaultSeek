"""AcquisitionEngine — coordinates AcquisitionJob lifecycle."""



from __future__ import annotations



from dataclasses import replace

from datetime import UTC, datetime

from uuid import UUID



from vaultseek.db.repositories.acquisition_job_repo import AcquisitionJobRepository

from vaultseek.db.uuid_utils import generate_uuid7

from vaultseek.models.entities.acquisition_job import (

    AcquisitionJob,

    AcquisitionJobState,

    AcquisitionJobType,

    validate_transition,

)

from vaultseek.services.provider_manager import ProviderManager





class AcquisitionEngine:

    """AcquisitionJob coordinator backed by persistent storage."""



    def __init__(

        self,

        provider_manager: ProviderManager,

        job_repo: AcquisitionJobRepository,

    ) -> None:

        self._providers = provider_manager

        self._jobs = job_repo



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

        self._jobs.create(job)

        return job



    def get(self, job_id: UUID) -> AcquisitionJob | None:

        return self._jobs.get(job_id)



    def list_jobs(self, *, library_id: UUID | None = None) -> list[AcquisitionJob]:

        return self._jobs.list_by_library(library_id)



    def queue(self, job_id: UUID) -> AcquisitionJob:

        return self._transition(job_id, AcquisitionJobState.QUEUED)



    def cancel(self, job_id: UUID) -> AcquisitionJob:

        return self._transition(job_id, AcquisitionJobState.CANCELLED)



    def advance(self, job_id: UUID, target: AcquisitionJobState, *, note: str = "") -> AcquisitionJob:

        return self._transition(job_id, target, note=note)


    def update_extra(self, job_id: UUID, updates: dict) -> AcquisitionJob:

        """Merge keys into AcquisitionJob.extra (e.g. local_paths after download)."""

        job = self._jobs.get(job_id)

        if job is None:

            raise KeyError(f"AcquisitionJob {job_id} not found")

        now = datetime.now(UTC)

        extra = dict(job.extra)

        extra.update(updates)

        updated = replace(job, extra=extra, updated_at=now)

        self._jobs.create(updated)

        return updated




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

        self._jobs.create(updated)

        return updated

