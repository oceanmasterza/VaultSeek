"""Unit tests for vaultseek.services.report_service and exporters."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import Engine

from vaultseek.core.exceptions import ReportError
from vaultseek.db.repositories.duplicate_repo import DuplicateRepository
from vaultseek.db.repositories.library_repo import LibraryRepository
from vaultseek.db.repositories.review_repo import ReviewRepository
from vaultseek.db.repositories.track_repo import TrackRepository
from vaultseek.db.uuid_utils import generate_uuid7
from vaultseek.models.entities.job import JobStatus, JobType
from vaultseek.models.entities.library import Library
from vaultseek.models.entities.review_item import ReviewItem, ReviewStatus, ReviewType
from vaultseek.models.entities.track import LibraryZone, Track
from vaultseek.services.dto.report_dto import ReportFormat, ReportRequest
from vaultseek.services.job_queue_service import JobQueueService
from vaultseek.services.report_exporters import (
    CsvReportExporter,
    HtmlReportExporter,
    JsonReportExporter,
)
from vaultseek.services.report_service import ReportService

_NOW = datetime(2026, 7, 18, tzinfo=UTC)


@pytest.fixture
def library_repo(engine: Engine) -> LibraryRepository:
    return LibraryRepository(engine)


@pytest.fixture
def zone_library(library_repo: LibraryRepository, library_id: UUID, tmp_path: Path) -> Library:
    library = Library(
        id=library_id,
        name="Vault",
        incoming_path=str(tmp_path / "incoming"),
        staging_path=str(tmp_path / "staging"),
        library_path=str(tmp_path / "library"),
        archive_path=str(tmp_path / "archive"),
        created_at=_NOW,
        updated_at=_NOW,
    )
    library_repo.upsert(library)
    return library


@pytest.fixture
def report_service(
    library_repo: LibraryRepository,
    track_repo: TrackRepository,
    review_repo: ReviewRepository,
    duplicate_repo: DuplicateRepository,
    job_queue: JobQueueService,
    tmp_path: Path,
) -> ReportService:
    return ReportService(
        library_repo,
        track_repo,
        review_repo,
        duplicate_repo,
        reports_dir=tmp_path / "reports",
        job_queue=job_queue,
    )


def _track(
    library: Library, *, zone: LibraryZone = LibraryZone.LIBRARY, **overrides: object
) -> Track:
    track_id = generate_uuid7()
    defaults: dict[str, object] = {
        "id": track_id,
        "library_id": library.id,
        "zone": zone,
        "file_path": f"C:/{zone.value}/{track_id}.flac",
        "file_name": f"{track_id}.flac",
        "file_size": 1000,
        "file_modified": _NOW,
        "created_at": _NOW,
        "updated_at": _NOW,
        "is_lossless": True,
        "has_embedded_art": False,
        "needs_review": False,
        "overall_confidence": 0.95,
        "quality_score": 80,
    }
    defaults.update(overrides)
    return Track(**defaults)  # type: ignore[arg-type]


def test_build_library_summary_aggregates_tracks_and_reviews(
    report_service: ReportService,
    track_repo: TrackRepository,
    review_repo: ReviewRepository,
    zone_library: Library,
) -> None:
    track_repo.upsert(_track(zone_library, zone=LibraryZone.INCOMING, is_lossless=False))
    track_repo.upsert(
        _track(
            zone_library,
            zone=LibraryZone.LIBRARY,
            has_embedded_art=True,
            quality_score=20,
            overall_confidence=0.5,
        )
    )
    track_repo.upsert(
        _track(zone_library, zone=LibraryZone.STAGING, needs_review=True, quality_score=None)
    )
    review_repo.create(
        ReviewItem(
            id=generate_uuid7(),
            library_id=zone_library.id,
            review_type=ReviewType.ARTWORK_MISSING,
            status=ReviewStatus.PENDING,
            title="missing art",
            created_at=_NOW,
        )
    )

    summary = report_service.build_library_summary(zone_library.id, now=_NOW)

    assert summary.library_name == "Vault"
    assert summary.track_count == 3
    assert summary.tracks_by_zone["incoming"] == 1
    assert summary.tracks_by_zone["staging"] == 1
    assert summary.tracks_by_zone["library"] == 1
    assert summary.lossless_count == 2
    assert summary.lossy_count == 1
    assert summary.needs_review_count == 1
    assert summary.has_embedded_art_count == 1
    assert summary.missing_embedded_art_count == 2
    assert summary.pending_reviews_by_type["artwork_missing"] == 1
    assert summary.quality_buckets["high"] == 1
    assert summary.quality_buckets["low"] == 1
    assert summary.quality_buckets["unscored"] == 1
    assert summary.average_confidence is not None
    assert 0.7 < summary.average_confidence < 0.9


def test_generate_writes_json_csv_and_html(
    report_service: ReportService,
    track_repo: TrackRepository,
    zone_library: Library,
    tmp_path: Path,
) -> None:
    track_repo.upsert(_track(zone_library))

    for fmt, exporter_cls in (
        (ReportFormat.JSON, JsonReportExporter),
        (ReportFormat.CSV, CsvReportExporter),
        (ReportFormat.HTML, HtmlReportExporter),
    ):
        out = tmp_path / f"summary{exporter_cls().file_extension}"
        result = report_service.generate(
            ReportRequest(
                library_id=zone_library.id,
                format=fmt,
                output_path=str(out),
            ),
            now=_NOW,
        )
        assert result.success is True
        assert out.is_file()
        assert out.stat().st_size > 0

    payload = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert payload["track_count"] == 1
    assert payload["library_name"] == "Vault"
    csv_text = (tmp_path / "summary.csv").read_text(encoding="utf-8")
    assert "track_count" in csv_text
    html_text = (tmp_path / "summary.html").read_text(encoding="utf-8")
    assert "Library summary" in html_text
    assert "Vault" in html_text


def test_generate_defaults_to_reports_dir(
    report_service: ReportService,
    track_repo: TrackRepository,
    zone_library: Library,
    tmp_path: Path,
) -> None:
    track_repo.upsert(_track(zone_library))

    result = report_service.generate(
        ReportRequest(library_id=zone_library.id, format=ReportFormat.JSON),
        now=_NOW,
    )

    assert result.output_path is not None
    path = Path(result.output_path)
    assert path.parent == tmp_path / "reports"
    assert path.suffix == ".json"
    assert path.is_file()


def test_enqueue_creates_generate_report_job(
    report_service: ReportService,
    zone_library: Library,
    job_repo: object,
) -> None:
    from vaultseek.db.repositories.job_repo import JobRepository

    assert isinstance(job_repo, JobRepository)
    job_id = report_service.enqueue(
        ReportRequest(library_id=zone_library.id, format=ReportFormat.CSV),
        now=_NOW,
    )
    job = job_repo.get(job_id)
    assert job is not None
    assert job.job_type is JobType.GENERATE_REPORT
    assert job.status is JobStatus.PENDING
    assert job.payload["format"] == "csv"


def test_unknown_library_raises(report_service: ReportService) -> None:
    with pytest.raises(ReportError, match="not found"):
        report_service.build_library_summary(generate_uuid7())


def test_unsupported_format_raises(report_service: ReportService, zone_library: Library) -> None:
    request = ReportRequest(library_id=zone_library.id, format=ReportFormat.JSON)
    # Force an unknown exporter by clearing the map.
    report_service._exporters = {}  # noqa: SLF001
    with pytest.raises(ReportError, match="Unsupported report format"):
        report_service.generate(request, now=_NOW)
