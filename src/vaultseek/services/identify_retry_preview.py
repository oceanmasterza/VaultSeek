"""Preview re-identification for pending Review tracks without mutating data.

Dry-run filename + library tracklist matching across analogous pending songs.
``apply_safe_matches`` assigns unique corroborated slots or enqueues identify
when ``dry_run=False`` (default stays preview-only). Reports per-row outcomes
and never aborts the batch on a single failure.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from vaultseek.core.exceptions import ReviewError
from vaultseek.db.repositories.acquisition_job_repo import AcquisitionJobRepository
from vaultseek.db.repositories.file_identity_repo import FileIdentityRepository
from vaultseek.db.repositories.review_repo import ReviewRepository
from vaultseek.db.repositories.track_repo import TrackRepository
from vaultseek.models.entities.job import JobType
from vaultseek.models.entities.review_item import ReviewItem, ReviewStatus, ReviewType
from vaultseek.models.entities.track import Track
from vaultseek.models.interfaces.metadata import MetadataQuery
from vaultseek.plugins.builtin.filename_parser import FilenameParserProvider
from vaultseek.services.acquisition_provenance import provenance_for_track_path
from vaultseek.services.job_queue_service import JobQueueService
from vaultseek.services.library_tracklist_matcher import (
    AlbumSlotRecommendation,
    LibraryMatchResult,
    LibraryTracklistMatcher,
)
from vaultseek.services.review_display import filename_song, looks_like_opaque_id
from vaultseek.services.review_queue_service import ReviewQueueService


@dataclass(frozen=True, slots=True)
class IdentifyPreviewRow:
    """One pending track's dry-run identification outcome."""

    track_id: UUID
    review_ids: tuple[UUID, ...]
    file_name: str
    stored_title: str
    predicted_title: str | None
    predicted_artist: str | None
    predicted_album: str | None
    overall_confidence: float
    would_auto_approve: bool
    recommendation_count: int
    top_recommendations: tuple[AlbumSlotRecommendation, ...]
    notes: tuple[str, ...]
    existing_is_better: bool = False


@dataclass(frozen=True, slots=True)
class IdentifyPreviewReport:
    """Batch preview for analogous pending Review songs."""

    library_id: UUID
    rows: tuple[IdentifyPreviewRow, ...]
    would_auto_approve: int
    stay_in_review: int
    opaque_title_fixed: int


@dataclass(frozen=True, slots=True)
class ApplyMatchRowResult:
    """Per-track outcome of ``apply_safe_matches`` (non-dry-run)."""

    track_id: UUID
    status: str
    error: str | None = None
    album_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class ApplyMatchesReport:
    """Preview plus per-row apply results."""

    preview: IdentifyPreviewReport
    results: tuple[ApplyMatchRowResult, ...]
    applied: int
    failed: int
    enqueued_identify: int


class IdentifyRetryPreviewService:
    """Read-only preview + explicit enqueue / safe-assign for pending retries."""

    def __init__(
        self,
        *,
        review_repo: ReviewRepository,
        track_repo: TrackRepository,
        file_identity_repo: FileIdentityRepository,
        library_matcher: LibraryTracklistMatcher,
        confidence_threshold: float = 0.90,
        job_queue: JobQueueService | None = None,
        acquisition_job_repo: AcquisitionJobRepository | None = None,
        review_queue: ReviewQueueService | None = None,
    ) -> None:
        self._reviews = review_repo
        self._tracks = track_repo
        self._identities = file_identity_repo
        self._matcher = library_matcher
        self._threshold = confidence_threshold
        self._job_queue = job_queue
        self._acquisition_jobs = acquisition_job_repo
        self._review_queue = review_queue
        self._filename = FilenameParserProvider()

    def preview_pending(
        self,
        library_id: UUID,
        *,
        analogous_only: bool = True,
        limit: int = 200,
    ) -> IdentifyPreviewReport:
        """Dry-run identify for pending unknown-artist/album items with audio."""
        pending = self._reviews.list_by_status(ReviewStatus.PENDING, library_id=library_id)
        by_track: dict[UUID, list[ReviewItem]] = {}
        for item in pending:
            if item.track_id is None:
                continue
            if analogous_only and item.review_type not in (
                ReviewType.UNKNOWN_ARTIST,
                ReviewType.UNKNOWN_ALBUM,
                ReviewType.METADATA_CONFLICT,
            ):
                continue
            by_track.setdefault(item.track_id, []).append(item)

        rows: list[IdentifyPreviewRow] = []
        auto = 0
        stay = 0
        opaque_fixed = 0
        for track_id, items in list(by_track.items())[:limit]:
            track = self._tracks.get_by_id(track_id)
            if track is None or not track.file_path or not Path(track.file_path).is_file():
                continue
            query, match, title = self._local_match(track)
            _ = query
            unique = match.unique
            artist = unique.artist_name if unique else None
            album = unique.album_title if unique else None
            existing_better = bool(unique and unique.existing_is_better)
            if unique is not None:
                if looks_like_opaque_id(title or ""):
                    title = unique.slot_title
                else:
                    title = title or unique.slot_title
                confidence = max(unique.score, unique.evidence_rank)
            elif title:
                confidence = 0.50
            else:
                confidence = 0.0
            # Identity succeeds even when a better LIBRARY copy exists.
            would_approve = unique is not None and confidence >= self._threshold
            notes: list[str] = []
            if looks_like_opaque_id(track.title or ""):
                notes.append("stored title was opaque id fragment")
                if isinstance(title, str) and title and not looks_like_opaque_id(title):
                    opaque_fixed += 1
                    notes.append(f"filename/library title -> {title}")
            identity = self._identities.get(track_id)
            if identity is not None and identity.fingerprint_data and not identity.acoustid_id:
                notes.append("fingerprint present but AcoustID id missing")
            if existing_better:
                notes.append("better LIBRARY copy exists — identify then archive duplicate")
            if would_approve:
                auto += 1
            else:
                stay += 1
                if match.recommendations:
                    notes.append(f"{len(match.recommendations)} album slot recommendations")
            rows.append(
                IdentifyPreviewRow(
                    track_id=track_id,
                    review_ids=tuple(item.id for item in items),
                    file_name=track.file_name,
                    stored_title=track.title or "",
                    predicted_title=title if isinstance(title, str) else None,
                    predicted_artist=artist,
                    predicted_album=album,
                    overall_confidence=float(confidence),
                    would_auto_approve=would_approve,
                    recommendation_count=len(match.recommendations),
                    top_recommendations=match.recommendations[:5],
                    notes=tuple(notes),
                    existing_is_better=existing_better,
                )
            )
        return IdentifyPreviewReport(
            library_id=library_id,
            rows=tuple(rows),
            would_auto_approve=auto,
            stay_in_review=stay,
            opaque_title_fixed=opaque_fixed,
        )

    def apply_safe_matches(
        self,
        library_id: UUID,
        *,
        dry_run: bool = True,
        limit: int = 200,
    ) -> ApplyMatchesReport:
        """Preview, then optionally assign unique corroborated slots or enqueue identify.

        ``dry_run=True`` (default) never mutates. When False, each row is
        revalidated and applied independently — one failure does not stop the batch.
        """
        report = self.preview_pending(library_id, limit=limit)
        if dry_run or self._review_queue is None:
            return ApplyMatchesReport(
                preview=report,
                results=(),
                applied=0,
                failed=0,
                enqueued_identify=0,
            )

        results: list[ApplyMatchRowResult] = []
        applied = 0
        failed = 0
        enqueued = 0
        for row in report.rows:
            # Revalidate before apply — do not trust a stale preview unique alone.
            track = self._tracks.get_by_id(row.track_id)
            if track is None:
                results.append(
                    ApplyMatchRowResult(
                        track_id=row.track_id, status="failed", error="track missing"
                    )
                )
                failed += 1
                continue
            _, match, _ = self._local_match(track)
            unique = match.unique
            if unique is not None and unique.score >= self._threshold:
                if not row.review_ids:
                    results.append(
                        ApplyMatchRowResult(
                            track_id=row.track_id,
                            status="failed",
                            error="no pending review item",
                        )
                    )
                    failed += 1
                    continue
                try:
                    self._review_queue.assign_album_slot(
                        row.review_ids[0],
                        album_id=unique.album_id,
                        title=_title_for_assign(track, unique),
                        track_number=unique.track_number,
                        disc_number=unique.disc_number,
                        artist_id=unique.artist_id,
                        resolved_by="identify_retry",
                    )
                except ReviewError as exc:
                    results.append(
                        ApplyMatchRowResult(
                            track_id=row.track_id,
                            status="failed",
                            error=str(exc),
                            album_id=unique.album_id,
                        )
                    )
                    failed += 1
                    continue
                except Exception as exc:  # noqa: BLE001 — batch continue
                    results.append(
                        ApplyMatchRowResult(
                            track_id=row.track_id,
                            status="failed",
                            error=str(exc),
                            album_id=unique.album_id,
                        )
                    )
                    failed += 1
                    continue
                results.append(
                    ApplyMatchRowResult(
                        track_id=row.track_id,
                        status="applied",
                        album_id=unique.album_id,
                    )
                )
                applied += 1
                continue

            if self._job_queue is not None:
                self._job_queue.enqueue(
                    JobType.IDENTIFY_METADATA,
                    library_id,
                    {"track_id": str(row.track_id)},
                )
                results.append(
                    ApplyMatchRowResult(track_id=row.track_id, status="enqueued_identify")
                )
                enqueued += 1
            else:
                results.append(
                    ApplyMatchRowResult(
                        track_id=row.track_id,
                        status="skipped",
                        error="no unique match and job queue unavailable",
                    )
                )
        return ApplyMatchesReport(
            preview=report,
            results=tuple(results),
            applied=applied,
            failed=failed,
            enqueued_identify=enqueued,
        )

    def enqueue_reidentify(
        self,
        track_ids: Sequence[UUID],
        library_id: UUID,
        *,
        dry_run: bool = True,
    ) -> int:
        """Enqueue identify_metadata jobs. ``dry_run=True`` (default) enqueues nothing."""
        if dry_run or self._job_queue is None:
            return 0
        count = 0
        for track_id in track_ids:
            self._job_queue.enqueue(
                JobType.IDENTIFY_METADATA,
                library_id,
                {"track_id": str(track_id)},
            )
            count += 1
        return count

    def backup_plan(self) -> tuple[str, ...]:
        """Human steps before any live re-identify mutation."""
        return (
            "Copy %APPDATA%\\VaultSeek\\vaultseek.db (+ -wal/-shm if present) to backups\\.",
            "Optionally zip the Incoming folder for the affected UUID download dirs.",
            "Run IdentifyRetryPreviewService.preview_pending and review the report.",
            "Only then call apply_safe_matches(..., dry_run=False) or enqueue_reidentify.",
            "Do not alter acquisition quality / waterfall settings.",
        )

    def _local_match(self, track: Track) -> tuple[MetadataQuery, LibraryMatchResult, str | None]:
        query = MetadataQuery(
            file_path=track.file_path,
            file_name=track.file_name,
            duration_ms=track.duration_ms,
            track_number=track.track_number,
        )
        filename_hit = self._filename.lookup_by_tags(query)
        title = _provider_field(filename_hit, "title")
        track_number = _provider_field(filename_hit, "track_number")
        if isinstance(title, str):
            query = MetadataQuery(
                file_path=track.file_path,
                file_name=track.file_name,
                title=title,
                duration_ms=track.duration_ms,
                track_number=(
                    int(track_number) if isinstance(track_number, int) else track.track_number
                ),
            )
        provenance = None
        if self._acquisition_jobs is not None:
            provenance = provenance_for_track_path(
                self._acquisition_jobs, track.library_id, track.file_path
            )
            if provenance is not None:
                query = MetadataQuery(
                    file_path=query.file_path,
                    file_name=query.file_name,
                    title=query.title,
                    artist=provenance.artist,
                    album=provenance.album,
                    duration_ms=query.duration_ms,
                    track_number=query.track_number,
                )
        match = self._matcher.match(track, query, provenance=provenance)
        predicted = title if isinstance(title, str) else None
        return query, match, predicted


def _title_for_assign(track: Track, unique: AlbumSlotRecommendation) -> str:
    filename_title = filename_song(track.file_name)
    if filename_title and not looks_like_opaque_id(filename_title):
        return filename_title
    if track.title and not looks_like_opaque_id(track.title):
        return track.title
    return unique.slot_title


def _provider_field(result: object | None, name: str) -> str | int | float | None:
    if result is None:
        return None
    for field in getattr(result, "fields", ()) or ():
        if getattr(field, "field", None) == name:
            return getattr(field, "value", None)
    return None


def human_preview_label(track: Track) -> str:
    if track.title and not looks_like_opaque_id(track.title):
        return track.title
    return filename_song(track.file_name)
