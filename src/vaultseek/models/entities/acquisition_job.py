"""AcquisitionJob — central VaultSeek acquisition workflow object.

See docs/ARCHITECTURAL_UPDATE_001.md and ADR-0017.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID


class AcquisitionJobType(str, Enum):
    """What the job is trying to acquire."""

    MISSING_ALBUM = "missing_album"
    MISSING_TRACK = "missing_track"
    QUALITY_UPGRADE = "quality_upgrade"


class AcquisitionJobState(str, Enum):
    """Deterministic AcquisitionJob state machine."""

    CREATED = "created"
    QUEUED = "queued"
    SEARCHING = "searching"
    COLLECTING_RESULTS = "collecting_results"
    SCORING = "scoring"
    WAITING_FOR_USER = "waiting_for_user"
    DOWNLOADING = "downloading"
    VERIFYING = "verifying"
    IMPORTING = "importing"
    COMPLETED = "completed"
    NO_RESULTS = "no_results"
    RETRY_SCHEDULED = "retry_scheduled"
    DOWNLOAD_FAILED = "download_failed"
    VERIFICATION_FAILED = "verification_failed"
    IMPORT_FAILED = "import_failed"
    CANCELLED = "cancelled"


ACQUISITION_TRANSITIONS: dict[AcquisitionJobState, frozenset[AcquisitionJobState]] = {
    AcquisitionJobState.CREATED: frozenset(
        {AcquisitionJobState.QUEUED, AcquisitionJobState.CANCELLED}
    ),
    AcquisitionJobState.QUEUED: frozenset(
        {AcquisitionJobState.SEARCHING, AcquisitionJobState.CANCELLED}
    ),
    AcquisitionJobState.SEARCHING: frozenset(
        {
            AcquisitionJobState.COLLECTING_RESULTS,
            AcquisitionJobState.NO_RESULTS,
            AcquisitionJobState.QUEUED,  # deferred by Soulseek search rate limit
            AcquisitionJobState.CANCELLED,
        }
    ),
    AcquisitionJobState.COLLECTING_RESULTS: frozenset(
        {
            AcquisitionJobState.SCORING,
            AcquisitionJobState.NO_RESULTS,
            AcquisitionJobState.CANCELLED,
        }
    ),
    AcquisitionJobState.SCORING: frozenset(
        {
            AcquisitionJobState.WAITING_FOR_USER,
            AcquisitionJobState.DOWNLOADING,
            AcquisitionJobState.NO_RESULTS,
            AcquisitionJobState.CANCELLED,
        }
    ),
    AcquisitionJobState.WAITING_FOR_USER: frozenset(
        {
            AcquisitionJobState.DOWNLOADING,
            AcquisitionJobState.CANCELLED,
            AcquisitionJobState.QUEUED,
        }
    ),
    AcquisitionJobState.DOWNLOADING: frozenset(
        {
            AcquisitionJobState.VERIFYING,
            AcquisitionJobState.DOWNLOAD_FAILED,
            AcquisitionJobState.CANCELLED,
        }
    ),
    AcquisitionJobState.VERIFYING: frozenset(
        {
            AcquisitionJobState.IMPORTING,
            AcquisitionJobState.COMPLETED,  # already owned (duplicate match)
            AcquisitionJobState.VERIFICATION_FAILED,
            AcquisitionJobState.CANCELLED,
        }
    ),
    AcquisitionJobState.IMPORTING: frozenset(
        {
            AcquisitionJobState.COMPLETED,
            AcquisitionJobState.IMPORT_FAILED,
            AcquisitionJobState.CANCELLED,
        }
    ),
    AcquisitionJobState.NO_RESULTS: frozenset(
        {AcquisitionJobState.RETRY_SCHEDULED, AcquisitionJobState.CANCELLED}
    ),
    AcquisitionJobState.DOWNLOAD_FAILED: frozenset(
        {
            AcquisitionJobState.RETRY_SCHEDULED,
            AcquisitionJobState.CANCELLED,
            AcquisitionJobState.SCORING,
            AcquisitionJobState.DOWNLOADING,
        }
    ),
    AcquisitionJobState.VERIFICATION_FAILED: frozenset(
        {
            AcquisitionJobState.RETRY_SCHEDULED,
            AcquisitionJobState.CANCELLED,
            AcquisitionJobState.SCORING,
            AcquisitionJobState.DOWNLOADING,
        }
    ),
    AcquisitionJobState.IMPORT_FAILED: frozenset(
        {
            AcquisitionJobState.RETRY_SCHEDULED,
            AcquisitionJobState.CANCELLED,
            AcquisitionJobState.SCORING,
            AcquisitionJobState.DOWNLOADING,
        }
    ),
    AcquisitionJobState.RETRY_SCHEDULED: frozenset(
        {AcquisitionJobState.QUEUED, AcquisitionJobState.CANCELLED}
    ),
    AcquisitionJobState.COMPLETED: frozenset(),
    AcquisitionJobState.CANCELLED: frozenset(),
}

_TERMINAL = frozenset({AcquisitionJobState.COMPLETED, AcquisitionJobState.CANCELLED})


@dataclass(frozen=True, slots=True)
class AcquisitionJob:
    """One acquisition workflow (missing media or quality upgrade)."""

    id: UUID
    library_id: UUID
    job_type: AcquisitionJobType
    state: AcquisitionJobState
    created_at: datetime
    updated_at: datetime
    artist: str | None = None
    album: str | None = None
    title: str | None = None
    year: int | None = None
    mb_release_id: str | None = None
    preferred_codec: str | None = None
    preferred_bit_depth: int | None = None
    preferred_country: str | None = None
    preferred_providers: tuple[str, ...] = ()
    selected_result_id: str | None = None
    selected_provider_id: str | None = None
    retry_count: int = 0
    priority: int = 100
    progress: float = 0.0
    error_message: str | None = None
    history: tuple[str, ...] = ()
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def is_terminal(self) -> bool:
        return self.state in _TERMINAL


def can_transition(source: AcquisitionJobState, target: AcquisitionJobState) -> bool:
    return target in ACQUISITION_TRANSITIONS.get(source, frozenset())


def validate_transition(source: AcquisitionJobState, target: AcquisitionJobState) -> None:
    if not can_transition(source, target):
        allowed = ", ".join(sorted(s.value for s in ACQUISITION_TRANSITIONS.get(source, frozenset())))
        raise ValueError(
            f"Illegal AcquisitionJob transition {source.value} -> {target.value} "
            f"(allowed from {source.value}: {allowed or 'none'})"
        )
