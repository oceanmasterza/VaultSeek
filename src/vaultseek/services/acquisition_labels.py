"""Human-readable labels and album rollup helpers for acquisition logging."""

from __future__ import annotations

from loguru import logger

from vaultseek.models.entities.acquisition_job import (
    AcquisitionJob,
    AcquisitionJobState,
    AcquisitionJobType,
)

_ACTIVE_ALBUM_STATES = frozenset(
    {
        AcquisitionJobState.CREATED,
        AcquisitionJobState.QUEUED,
        AcquisitionJobState.SEARCHING,
        AcquisitionJobState.COLLECTING_RESULTS,
        AcquisitionJobState.SCORING,
        AcquisitionJobState.WAITING_FOR_USER,
        AcquisitionJobState.DOWNLOADING,
        AcquisitionJobState.VERIFYING,
        AcquisitionJobState.IMPORTING,
        AcquisitionJobState.RETRY_SCHEDULED,
    }
)


def job_label(job: AcquisitionJob) -> str:
    """Artist — album — title, or job id when metadata is sparse."""
    parts = [p for p in (job.artist, job.album, job.title) if p]
    return " — ".join(parts) if parts else str(job.id)


def album_label(job: AcquisitionJob) -> str:
    """Artist — album (no track title)."""
    parts = [p for p in (job.artist, job.album) if p]
    return " — ".join(parts) if parts else str(job.id)


def album_group_key(job: AcquisitionJob) -> tuple[str, str] | None:
    """Stable key for grouping missing-track jobs on the same release."""
    if job.mb_release_id:
        return ("mbid", job.mb_release_id)
    if job.album:
        return ("album", f"{job.artist or ''}|{job.album}")
    return None


def maybe_log_album_fully_acquired(
    engine: object,
    job: AcquisitionJob,
) -> None:
    """Log once when every missing-track job for an album reaches COMPLETED."""
    if job.state is not AcquisitionJobState.COMPLETED:
        return
    key = album_group_key(job)
    if key is None:
        return

    list_jobs = getattr(engine, "list_jobs", None)
    if list_jobs is None:
        return

    siblings = [
        sibling
        for sibling in list_jobs(library_id=job.library_id)
        if sibling.job_type is AcquisitionJobType.MISSING_TRACK
        and album_group_key(sibling) == key
    ]
    if not siblings:
        return
    if any(sibling.state in _ACTIVE_ALBUM_STATES for sibling in siblings):
        return
    if not all(sibling.state is AcquisitionJobState.COMPLETED for sibling in siblings):
        return

    logger.info("Album fully acquired: {}", album_label(job))
