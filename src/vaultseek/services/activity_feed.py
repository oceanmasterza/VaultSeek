"""Unified activity feed — merge library pipeline jobs and wishlist jobs.

Jobs and Wishlist remain the places to act; this feed is a Lidarr-style
“what’s happening” timeline sorted by most recent event time.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

from vaultseek.models.entities.acquisition_job import AcquisitionJob
from vaultseek.models.entities.job import Job, JobStatus

if TYPE_CHECKING:
    from vaultseek.core.container import Container

_DEFAULT_CAP = 150
_PIPELINE_STATUS_LIMITS: tuple[tuple[JobStatus, int | None], ...] = (
    (JobStatus.RUNNING, None),
    (JobStatus.PENDING, 100),
    (JobStatus.RETRY, 50),
    (JobStatus.FAILED, 50),
    (JobStatus.COMPLETED, 50),
)


class ActivitySource(StrEnum):
    PIPELINE = "pipeline"
    WISHLIST = "wishlist"


@dataclass(frozen=True, slots=True)
class ActivityItem:
    """One row in the combined Activity timeline."""

    source: ActivitySource
    when: datetime
    kind: str
    status: str
    summary: str
    detail: str
    navigate_key: str  # jobs | acquisition


def _pipeline_when(job: Job) -> datetime:
    return job.completed_at or job.started_at or job.created_at


def _pipeline_summary(job: Job) -> str:
    payload = job.payload or {}
    for key in ("directory", "file_path", "path", "album", "artist"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return f"{job.job_type.value}: {value.strip()}"
    return job.job_type.value.replace("_", " ")


def item_from_pipeline_job(job: Job) -> ActivityItem:
    return ActivityItem(
        source=ActivitySource.PIPELINE,
        when=_pipeline_when(job),
        kind=job.job_type.value,
        status=job.status.value,
        summary=_pipeline_summary(job),
        detail=(job.error_message or "").strip(),
        navigate_key="jobs",
    )


def _wishlist_summary(job: AcquisitionJob) -> str:
    parts = [p for p in (job.artist, job.album, job.title) if p]
    label = " — ".join(parts) if parts else job.job_type.value.replace("_", " ")
    return f"{job.job_type.value.replace('_', ' ')}: {label}"


def item_from_wishlist_job(job: AcquisitionJob) -> ActivityItem:
    detail = (job.error_message or "").strip()
    if not detail and job.history:
        detail = job.history[-1]
    return ActivityItem(
        source=ActivitySource.WISHLIST,
        when=job.updated_at,
        kind=job.job_type.value,
        status=job.state.value,
        summary=_wishlist_summary(job),
        detail=detail,
        navigate_key="acquisition",
    )


def merge_activity_items(
    *,
    pipeline_jobs: list[Job],
    wishlist_jobs: list[AcquisitionJob],
    cap: int = _DEFAULT_CAP,
    source_filter: ActivitySource | None = None,
) -> list[ActivityItem]:
    """Merge, optionally filter by source, sort newest first, and cap."""
    items: list[ActivityItem] = []
    if source_filter is None or source_filter is ActivitySource.PIPELINE:
        items.extend(item_from_pipeline_job(job) for job in pipeline_jobs)
    if source_filter is None or source_filter is ActivitySource.WISHLIST:
        items.extend(item_from_wishlist_job(job) for job in wishlist_jobs)
    items.sort(key=lambda item: item.when, reverse=True)
    if cap > 0:
        return items[:cap]
    return items


def collect_pipeline_jobs(container: Container, library_id: UUID) -> list[Job]:
    """Fetch recent pipeline jobs for the activity feed."""
    seen: set[UUID] = set()
    jobs: list[Job] = []
    for status, limit in _PIPELINE_STATUS_LIMITS:
        for job in container.job_repo.list_by_status(
            status, library_id=library_id, limit=limit
        ):
            if job.id in seen:
                continue
            seen.add(job.id)
            jobs.append(job)
    return jobs


def build_activity_feed(
    container: Container,
    library_id: UUID,
    *,
    cap: int = _DEFAULT_CAP,
    source_filter: ActivitySource | None = None,
) -> list[ActivityItem]:
    """Load pipeline + wishlist jobs and return a merged timeline."""
    pipeline = collect_pipeline_jobs(container, library_id)
    wishlist = list(container.acquisition_engine.list_jobs(library_id=library_id))
    return merge_activity_items(
        pipeline_jobs=pipeline,
        wishlist_jobs=wishlist,
        cap=cap,
        source_filter=source_filter,
    )
