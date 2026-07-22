"""Create Attention-needed review items for acquisition failures."""

from __future__ import annotations

from uuid import UUID

from loguru import logger

from vaultseek.models.entities.acquisition_job import AcquisitionJob, AcquisitionJobState
from vaultseek.models.entities.review_item import ReviewType
from vaultseek.services.acquisition_labels import job_label
from vaultseek.services.dto.review_dto import ReviewItemCreate
from vaultseek.services.review_queue_service import ReviewQueueService

_NO_RESULTS_STATES = frozenset({AcquisitionJobState.NO_RESULTS})
_FAILED_STATES = frozenset(
    {
        AcquisitionJobState.DOWNLOAD_FAILED,
        AcquisitionJobState.VERIFICATION_FAILED,
        AcquisitionJobState.IMPORT_FAILED,
    }
)
_NEEDS_CHOICE_STATES = frozenset({AcquisitionJobState.WAITING_FOR_USER})


def review_type_for_state(state: AcquisitionJobState) -> ReviewType | None:
    """Map a terminal-ish acquisition failure state to a ReviewType."""
    if state in _NO_RESULTS_STATES:
        return ReviewType.ACQUISITION_NO_RESULTS
    if state in _FAILED_STATES:
        return ReviewType.ACQUISITION_FAILED
    if state in _NEEDS_CHOICE_STATES:
        return ReviewType.ACQUISITION_NEEDS_CHOICE
    return None


def park_acquisition_failure(
    review_queue: ReviewQueueService | None,
    job: AcquisitionJob,
    *,
    message: str = "",
    provider_offline: bool = False,
) -> UUID | None:
    """Create or refresh a pending ReviewItem for an acquisition failure.

    Dedupes on ``payload.acquisition_job_id`` so retries do not flood Attention.
    Returns the review id, or ``None`` when no review is warranted / queue missing.
    """
    if review_queue is None:
        return None

    review_type = review_type_for_state(job.state)
    if review_type is None and not provider_offline:
        return None
    if provider_offline:
        review_type = ReviewType.ACQUISITION_FAILED

    assert review_type is not None

    label = job_label(job)
    note = (message or job.error_message or "").strip()
    if provider_offline and not note:
        note = "No acquisition providers connected (Nicotine+ offline or disabled)."
    if not note:
        note = job.state.value.replace("_", " ")

    if review_type is ReviewType.ACQUISITION_NO_RESULTS:
        title = f"No acquisition results: {label}"
        description = (
            f"Search returned nothing for {label}. {note} "
            "Check Nicotine+ / Soulseek connectivity, or try different search terms."
        )
    elif review_type is ReviewType.ACQUISITION_NEEDS_CHOICE:
        title = f"Acquisition needs your pick: {label}"
        description = (
            f"{label} — best match is below the auto-acquire threshold. {note} "
            "Open Acquisition → Pick result to choose a download."
        )
    else:
        title = f"Acquisition failed: {label}"
        description = f"{label} — {note}"

    review_id = review_queue.create_item(
        ReviewItemCreate(
            library_id=job.library_id,
            review_type=review_type,
            title=title,
            description=description,
            payload={
                "acquisition_job_id": str(job.id),
                "acquisition_state": job.state.value,
                "artist": job.artist,
                "album": job.album,
                "title": job.title,
                "provider_offline": provider_offline,
            },
        )
    )
    logger.debug(
        "Parked acquisition attention review {} for job {} ({})",
        review_id,
        job.id,
        job.state.value,
    )
    return review_id


def park_if_attention_needed(
    review_queue: ReviewQueueService | None,
    job: AcquisitionJob | None,
    *,
    message: str = "",
    provider_offline: bool = False,
) -> UUID | None:
    """Convenience wrapper when the job may be missing."""
    if job is None:
        return None
    if provider_offline or review_type_for_state(job.state) is not None:
        return park_acquisition_failure(
            review_queue,
            job,
            message=message,
            provider_offline=provider_offline,
        )
    return None
