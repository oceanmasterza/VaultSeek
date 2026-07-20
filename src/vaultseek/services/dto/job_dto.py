"""DTOs for `JobQueueService` (see docs/architecture/04-service-layer.md,
"DTOs" and "JobQueueService").
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from vaultseek.models.entities.job import JobType


@dataclass(frozen=True, slots=True)
class JobCreate:
    """One job to enqueue via :meth:`JobQueueService.enqueue_batch`.

    Not in the architecture docs by name — `enqueue_batch` references a
    `JobCreate` type without defining it. Mirrors :meth:`JobQueueService.enqueue`'s
    own keyword arguments exactly, so a caller building many jobs at once
    doesn't need N individual method calls.
    """

    job_type: JobType
    library_id: UUID
    payload: dict[str, Any] = field(default_factory=dict)
    priority: int = 100
    parent_job_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class JobStatsDTO:
    """Live job-queue counters for one library — what a Job Monitor
    dashboard polls. `by_type` counts only `pending` + `running` jobs
    (the current backlog/in-flight work), not a lifetime total — see
    :meth:`JobQueueService.get_stats`.
    """

    pending: int
    running: int
    failed: int
    completed_today: int
    by_type: dict[str, int]
