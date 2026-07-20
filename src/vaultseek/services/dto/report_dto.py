"""DTOs for library reports (Phase 13)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID


class ReportType(StrEnum):
    """Documented report types — none were specified in the roadmap;
    ``library_summary`` is the Phase 13 MVP fill-in."""

    LIBRARY_SUMMARY = "library_summary"


class ReportFormat(StrEnum):
    JSON = "json"
    CSV = "csv"
    HTML = "html"


@dataclass(frozen=True, slots=True)
class LibrarySummaryReport:
    """Aggregated library health snapshot used by all exporters."""

    library_id: UUID
    library_name: str
    generated_at: datetime
    track_count: int
    tracks_by_zone: dict[str, int]
    lossless_count: int
    lossy_count: int
    needs_review_count: int
    has_embedded_art_count: int
    missing_embedded_art_count: int
    pending_reviews_by_type: dict[str, int]
    open_duplicate_groups: int
    quality_buckets: dict[str, int]
    average_confidence: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_type": ReportType.LIBRARY_SUMMARY.value,
            "library_id": str(self.library_id),
            "library_name": self.library_name,
            "generated_at": self.generated_at.isoformat(),
            "track_count": self.track_count,
            "tracks_by_zone": dict(self.tracks_by_zone),
            "lossless_count": self.lossless_count,
            "lossy_count": self.lossy_count,
            "needs_review_count": self.needs_review_count,
            "has_embedded_art_count": self.has_embedded_art_count,
            "missing_embedded_art_count": self.missing_embedded_art_count,
            "pending_reviews_by_type": dict(self.pending_reviews_by_type),
            "open_duplicate_groups": self.open_duplicate_groups,
            "quality_buckets": dict(self.quality_buckets),
            "average_confidence": self.average_confidence,
        }


@dataclass(frozen=True, slots=True)
class ReportRequest:
    """Input for :meth:`ReportService.generate` / job payload."""

    library_id: UUID
    report_type: ReportType = ReportType.LIBRARY_SUMMARY
    format: ReportFormat = ReportFormat.JSON
    output_path: str | None = None


@dataclass(frozen=True, slots=True)
class ReportResult:
    """Outcome of a report generation run."""

    success: bool
    output_path: str | None = None
    format: ReportFormat | None = None
    report_type: ReportType | None = None
    message: str | None = None
    summary: LibrarySummaryReport | None = None
    details: dict[str, Any] = field(default_factory=dict)
