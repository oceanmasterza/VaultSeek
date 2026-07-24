"""Create Attention-needed review items for acquisition failures.

Only escalate when the song appears genuinely unavailable after repeated
empty Soulseek searches (``EXHAUSTED_NOT_ON_NETWORK``). Transient outcomes
(empty search, peer offline, not shared, verify hiccups, below threshold)
must keep retrying in the background — they must not flood Review.
"""

from __future__ import annotations

from uuid import UUID

from loguru import logger

from vaultseek.models.entities.acquisition_job import AcquisitionJob, AcquisitionJobState
from vaultseek.models.entities.review_item import ReviewType
from vaultseek.services.acquisition_labels import job_label
from vaultseek.services.acquisition_outcomes import (
    AcquisitionOutcomeCode,
    job_outcome_code,
    outcome_label,
    should_park_in_review,
)
from vaultseek.services.dto.review_dto import ReviewItemCreate
from vaultseek.services.review_queue_service import ReviewQueueService


def review_type_for_state(state: AcquisitionJobState) -> ReviewType | None:
    """Legacy mapper — prefer :func:`should_park_job` + outcome codes."""
    if state is AcquisitionJobState.NO_RESULTS:
        return ReviewType.ACQUISITION_NO_RESULTS
    return None


def should_park_job(job: AcquisitionJob, *, provider_offline: bool = False) -> bool:
    """Return True only when this job belongs in the human Review queue."""
    del provider_offline  # offline is retryable; do not park
    code = job_outcome_code(job)
    if code is not None:
        return should_park_in_review(code)
    # Back-compat: only park NO_RESULTS that were explicitly marked exhausted.
    if job.state is AcquisitionJobState.NO_RESULTS:
        return bool(job.extra.get("search_exhausted"))
    return False


def park_acquisition_failure(
    review_queue: ReviewQueueService | None,
    job: AcquisitionJob,
    *,
    message: str = "",
    provider_offline: bool = False,
) -> UUID | None:
    """Create or refresh a pending ReviewItem when the song is unavailable."""
    if review_queue is None:
        return None
    if not should_park_job(job, provider_offline=provider_offline):
        return None

    code = job_outcome_code(job) or AcquisitionOutcomeCode.EXHAUSTED_NOT_ON_NETWORK
    label = job_label(job)
    note = (message or job.error_message or outcome_label(code) or "").strip()
    title = f"Not on Soulseek: {label}"
    description = (
        f"{label} — {note or 'no hits after repeated searches'}. "
        "Automation will keep a slow recheck, but this likely needs a different source."
    )

    review_id = review_queue.create_item(
        ReviewItemCreate(
            library_id=job.library_id,
            review_type=ReviewType.ACQUISITION_NO_RESULTS,
            title=title,
            description=description,
            payload={
                "acquisition_job_id": str(job.id),
                "acquisition_state": job.state.value,
                "outcome_code": code.value,
                "outcome_label": outcome_label(code),
                "artist": job.artist,
                "album": job.album,
                "title": job.title,
                "provider_offline": False,
                "empty_search_attempts": int(job.extra.get("empty_search_attempts") or 0),
            },
        )
    )
    logger.info(
        "Parked unavailable-song review {} for job {} ({})",
        review_id,
        job.id,
        code.value,
    )
    return review_id


def park_if_attention_needed(
    review_queue: ReviewQueueService | None,
    job: AcquisitionJob | None,
    *,
    message: str = "",
    provider_offline: bool = False,
) -> UUID | None:
    """Park only exhausted unavailability — never transient acquisition issues."""
    if job is None:
        return None
    if not should_park_job(job, provider_offline=provider_offline):
        return None
    return park_acquisition_failure(
        review_queue,
        job,
        message=message,
        provider_offline=provider_offline,
    )
