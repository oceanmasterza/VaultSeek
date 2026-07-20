"""Job entity — a single unit of background work.

Mirrors the `jobs` table column-for-column (see
docs/architecture/03-database-schema.md, "Job Queue"). Pulled forward
from Phase 3 into Phase 2 because :class:`~vaultseek.db.repositories.job_repo.JobRepository`
needs a real return type; the job *execution* engine that actually
enqueues and runs these (see docs/architecture/12-pipeline-engine-v3.md)
is still Phase 4.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID


class JobType(StrEnum):
    """See docs/architecture/03-database-schema.md, "Job Types" table
    for the enqueues-what-next pipeline this vocabulary drives."""

    SCAN_DIRECTORY = "scan_directory"
    HASH_FILE = "hash_file"
    FINGERPRINT_FILE = "fingerprint_file"
    IDENTIFY_METADATA = "identify_metadata"
    FETCH_ARTWORK = "fetch_artwork"
    DETECT_DUPLICATES = "detect_duplicates"
    EVALUATE_RULES = "evaluate_rules"
    ORGANIZE_FILE = "organize_file"
    SYNC_MEDIA_SERVER = "sync_media_server"
    GENERATE_REPORT = "generate_report"


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRY = "retry"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class Job:
    """A single unit of background work, persisted in the `jobs` table."""

    id: UUID
    library_id: UUID
    job_type: JobType
    status: JobStatus
    payload: dict[str, Any]
    created_at: datetime
    priority: int = 100
    parent_job_id: UUID | None = None
    attempt_count: int = 0
    max_attempts: int = 3
    error_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    scheduled_at: datetime | None = None
