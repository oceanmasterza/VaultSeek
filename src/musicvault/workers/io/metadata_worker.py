"""MetadataWorker — runs `identify_metadata` jobs through MetadataArbitrator.

I/O-bound (Tier 2 — HTTP + Mutagen). Does **not** enqueue
`fetch_artwork` / `detect_duplicates` / `evaluate_rules` yet — those
workers arrive in later phases. When overall confidence is below
threshold, sets ``tracks.needs_review`` and creates a
:class:`~musicvault.models.entities.review_item.ReviewItem` via
:class:`~musicvault.services.review_queue_service.ReviewQueueService`.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

from musicvault.db.repositories.file_identity_repo import FileIdentityRepository
from musicvault.db.repositories.metadata_confidence_repo import MetadataConfidenceRepository
from musicvault.db.repositories.track_repo import TrackRepository
from musicvault.models.entities.job import Job
from musicvault.models.entities.track import Track
from musicvault.models.interfaces.metadata import FingerprintData
from musicvault.models.value_objects.field_confidence import FieldConfidence
from musicvault.models.value_objects.file_identity import FileIdentity
from musicvault.services.job_queue_service import JobQueueService
from musicvault.services.metadata_arbitrator import MetadataArbitrator
from musicvault.services.review_queue_service import ReviewQueueService


class MetadataWorker:
    def __init__(
        self,
        track_repo: TrackRepository,
        file_identity_repo: FileIdentityRepository,
        metadata_confidence_repo: MetadataConfidenceRepository,
        arbitrator: MetadataArbitrator,
        job_queue: JobQueueService,
        review_queue: ReviewQueueService,
    ) -> None:
        self._tracks = track_repo
        self._identities = file_identity_repo
        self._confidence = metadata_confidence_repo
        self._arbitrator = arbitrator
        self._job_queue = job_queue
        self._reviews = review_queue

    def execute(self, job: Job) -> None:
        track_id = UUID(job.payload["track_id"])
        track = self._tracks.get_by_id(track_id)
        if track is None:
            self._job_queue.mark_failed(job.id, f"Track {track_id} not found")
            return

        identity = self._identities.get(track_id)
        fingerprint = _fingerprint_from_identity(identity)
        result = self._arbitrator.resolve(track, fingerprint)

        now = datetime.now(UTC)
        updated = _apply_fields(
            track, result.fields, result.overall_confidence, result.needs_review, now
        )
        self._tracks.upsert(updated)
        self._confidence.upsert_fields(track_id, list(result.fields.values()), now=now)

        if identity is not None:
            acoustid_id = _winner_str(result.fields, "acoustid_id")
            acoustid_score = _winner_float(result.fields, "acoustid_score")
            if acoustid_id is not None or acoustid_score is not None:
                next_id = acoustid_id if acoustid_id is not None else identity.acoustid_id
                next_score = (
                    acoustid_score if acoustid_score is not None else identity.acoustid_score
                )
                self._identities.upsert(
                    replace(identity, acoustid_id=next_id, acoustid_score=next_score)
                )

        if result.needs_review:
            self._reviews.create_from_arbitration(
                library_id=job.library_id,
                track_id=track_id,
                result=result,
                now=now,
            )

        self._job_queue.mark_completed(job.id)


def _fingerprint_from_identity(identity: FileIdentity | None) -> FingerprintData | None:
    if identity is None or identity.fingerprint_data is None:
        return None
    duration = identity.fingerprint_duration if identity.fingerprint_duration is not None else 0.0
    return FingerprintData(
        fingerprint_data=identity.fingerprint_data,
        duration_seconds=duration,
        fingerprint_hash=identity.fingerprint_hash,
        acoustid_id=identity.acoustid_id,
        acoustid_score=identity.acoustid_score,
    )


def _apply_fields(
    track: Track,
    fields: dict[str, FieldConfidence],
    overall_confidence: float,
    needs_review: bool,
    now: datetime,
) -> Track:
    updates: dict[str, object] = {
        "overall_confidence": overall_confidence,
        "needs_review": needs_review,
        "updated_at": now,
    }
    if "title" in fields:
        updates["title"] = fields["title"].value
    if "year" in fields and isinstance(fields["year"].value, int):
        updates["year"] = fields["year"].value
    if "genre" in fields:
        updates["genre"] = fields["genre"].value
    if "composer" in fields:
        updates["composer"] = fields["composer"].value
    if "track_number" in fields and isinstance(fields["track_number"].value, int):
        updates["track_number"] = fields["track_number"].value
    if "mb_recording_id" in fields and isinstance(fields["mb_recording_id"].value, str):
        updates["mb_recording_id"] = fields["mb_recording_id"].value
    return replace(track, **updates)  # type: ignore[arg-type]


def _winner_str(fields: dict[str, FieldConfidence], name: str) -> str | None:
    item = fields.get(name)
    if item is None or not isinstance(item.value, str):
        return None
    return item.value


def _winner_float(fields: dict[str, FieldConfidence], name: str) -> float | None:
    item = fields.get(name)
    if item is None:
        return None
    if isinstance(item.value, (int, float)):
        return float(item.value)
    return None
