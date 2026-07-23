"""Wanted shelf — park Discogs/album picks until the user starts download.

Parked jobs are normal ``MISSING_ALBUM`` AcquisitionJobs with
``extra["parked"] = True``. Automation must skip them; promote clears the
flag and queues for search.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from vaultseek.models.entities.acquisition_job import (
    AcquisitionJob,
    AcquisitionJobState,
    AcquisitionJobType,
)
from vaultseek.services.acquisition_engine import AcquisitionEngine

PARKED_KEY = "parked"
SOURCE_WANTED = "wanted"


def is_parked(job: AcquisitionJob | None) -> bool:
    if job is None:
        return False
    return bool(job.extra.get(PARKED_KEY))


def list_wanted(
    engine: AcquisitionEngine,
    library_id: UUID,
    *,
    artist: str | None = None,
) -> list[AcquisitionJob]:
    """Parked, non-cancelled wanted jobs, newest first."""
    needle = (artist or "").strip().casefold()
    rows: list[AcquisitionJob] = []
    for job in engine.list_jobs(library_id=library_id):
        if not is_parked(job):
            continue
        if job.state is AcquisitionJobState.CANCELLED:
            continue
        if needle and (job.artist or "").strip().casefold() != needle:
            continue
        rows.append(job)
    rows.sort(key=lambda job: job.updated_at, reverse=True)
    return rows


def park_album_job(
    engine: AcquisitionEngine,
    *,
    library_id: UUID,
    artist: str | None,
    album: str | None,
    year: int | None = None,
    preferred_codec: str | None = None,
    priority: int = 90,
    extra: dict[str, Any] | None = None,
) -> AcquisitionJob:
    """Create a parked missing-album job (never auto-queued)."""
    job = engine.create_job(
        library_id=library_id,
        job_type=AcquisitionJobType.MISSING_ALBUM,
        artist=artist,
        album=album,
        year=year,
        preferred_codec=preferred_codec,
        priority=priority,
    )
    payload: dict[str, Any] = {
        PARKED_KEY: True,
        "source": SOURCE_WANTED,
    }
    if extra:
        payload.update(extra)
    return engine.update_extra(job.id, payload)


def promote_wanted(engine: AcquisitionEngine, job_id: UUID) -> AcquisitionJob:
    """Clear parked flag and queue for search/download."""
    job = engine.get(job_id)
    if job is None:
        raise KeyError(f"AcquisitionJob {job_id} not found")
    if not is_parked(job):
        if job.state is AcquisitionJobState.CREATED:
            return engine.queue(job_id)
        return job
    engine.update_extra(job_id, {PARKED_KEY: False})
    job = engine.get(job_id)
    if job is None:
        raise KeyError(f"AcquisitionJob {job_id} not found")
    if job.state is AcquisitionJobState.CREATED:
        return engine.queue(job_id)
    return job


def remove_wanted(engine: AcquisitionEngine, job_id: UUID) -> AcquisitionJob:
    """Cancel a parked wanted job."""
    job = engine.get(job_id)
    if job is None:
        raise KeyError(f"AcquisitionJob {job_id} not found")
    if job.state is AcquisitionJobState.CANCELLED:
        return job
    return engine.cancel(job_id)
