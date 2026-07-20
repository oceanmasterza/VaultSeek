"""ReportService — build library summaries and write them to disk.

Phase 13 MVP (docs/architecture/04-service-layer.md ``ReportService``;
roadmap goal HTML/CSV/Excel/PDF). Built-in exporters cover JSON, CSV,
and HTML; Excel/PDF stay deferred. ``library_stats`` is computed on
demand rather than materialized — the deferred table remains uncreated
until the Phase 14 dashboard needs sub-500ms cached counters.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from vaultseek.core.exceptions import ReportError
from vaultseek.db.repositories.duplicate_repo import DuplicateRepository
from vaultseek.db.repositories.library_repo import LibraryRepository
from vaultseek.db.repositories.review_repo import ReviewRepository
from vaultseek.db.repositories.track_repo import TrackRepository
from vaultseek.db.uuid_utils import generate_uuid7
from vaultseek.models.entities.job import JobType
from vaultseek.models.entities.track import LibraryZone
from vaultseek.services.dto.report_dto import (
    LibrarySummaryReport,
    ReportRequest,
    ReportResult,
    ReportType,
)
from vaultseek.services.job_queue_service import JobQueueService
from vaultseek.services.report_exporters import BUILTIN_EXPORTERS, ReportExporter


class ReportService:
    def __init__(
        self,
        library_repo: LibraryRepository,
        track_repo: TrackRepository,
        review_repo: ReviewRepository,
        duplicate_repo: DuplicateRepository,
        *,
        reports_dir: Path,
        exporters: list[ReportExporter] | None = None,
        job_queue: JobQueueService | None = None,
    ) -> None:
        self._libraries = library_repo
        self._tracks = track_repo
        self._reviews = review_repo
        self._duplicates = duplicate_repo
        self._reports_dir = reports_dir
        chosen = exporters if exporters is not None else list(BUILTIN_EXPORTERS)
        self._exporters: dict[str, ReportExporter] = {
            exporter.format_id: exporter for exporter in chosen
        }
        self._job_queue = job_queue

    def build_library_summary(
        self, library_id: UUID, *, now: datetime | None = None
    ) -> LibrarySummaryReport:
        """Aggregate on-demand stats for one library."""
        library = self._libraries.get(library_id)
        if library is None:
            raise ReportError(f"Library {library_id} not found")
        generated_at = now or datetime.now(UTC)
        aggregates = self._tracks.summarize_for_report(library_id)
        by_zone = self._tracks.count_by_zone(library_id)
        # Ensure every zone key is present for stable exports.
        tracks_by_zone = {zone.value: by_zone.get(zone.value, 0) for zone in LibraryZone}
        for zone, count in by_zone.items():
            tracks_by_zone[zone] = count

        raw_buckets = aggregates["quality_buckets"]
        quality_buckets = {str(key): int(value) for key, value in raw_buckets.items()}
        avg = aggregates["average_confidence"]

        return LibrarySummaryReport(
            library_id=library_id,
            library_name=library.name,
            generated_at=generated_at,
            track_count=aggregates["track_count"],
            tracks_by_zone=tracks_by_zone,
            lossless_count=aggregates["lossless_count"],
            lossy_count=aggregates["lossy_count"],
            needs_review_count=aggregates["needs_review_count"],
            has_embedded_art_count=aggregates["has_embedded_art_count"],
            missing_embedded_art_count=aggregates["missing_embedded_art_count"],
            pending_reviews_by_type=self._reviews.count_pending_by_type(library_id),
            open_duplicate_groups=len(self._duplicates.list_open_by_library(library_id)),
            quality_buckets=quality_buckets,
            average_confidence=float(avg) if avg is not None else None,
        )

    def generate(self, request: ReportRequest, *, now: datetime | None = None) -> ReportResult:
        """Build and write a report; returns the output path."""
        if request.report_type is not ReportType.LIBRARY_SUMMARY:
            raise ReportError(f"Unsupported report type: {request.report_type.value}")
        exporter = self._exporters.get(request.format.value)
        if exporter is None:
            raise ReportError(f"Unsupported report format: {request.format.value}")

        generated_at = now or datetime.now(UTC)
        summary = self.build_library_summary(request.library_id, now=generated_at)
        payload = exporter.export(summary)
        output = self._resolve_output_path(request, exporter, generated_at)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(payload)

        return ReportResult(
            success=True,
            output_path=str(output),
            format=request.format,
            report_type=request.report_type,
            message=f"Wrote {request.format.value} report to {output}",
            summary=summary,
            details={"bytes": len(payload), "mime_type": exporter.mime_type},
        )

    def enqueue(
        self,
        request: ReportRequest,
        *,
        now: datetime | None = None,
    ) -> UUID:
        """Enqueue a ``generate_report`` job (user/CLI entry point)."""
        if self._job_queue is None:
            raise ReportError("Job queue is not wired; cannot enqueue reports")
        return self._job_queue.enqueue(
            JobType.GENERATE_REPORT,
            request.library_id,
            {
                "report_type": request.report_type.value,
                "format": request.format.value,
                "output_path": request.output_path,
            },
            now=now or datetime.now(UTC),
        )

    def _resolve_output_path(
        self,
        request: ReportRequest,
        exporter: ReportExporter,
        generated_at: datetime,
    ) -> Path:
        if request.output_path:
            return Path(request.output_path)
        stamp = generated_at.strftime("%Y%m%dT%H%M%SZ")
        name = (
            f"{request.report_type.value}_{request.library_id.hex[:8]}_"
            f"{stamp}_{generate_uuid7().hex[:8]}{exporter.file_extension}"
        )
        return self._reports_dir / name
