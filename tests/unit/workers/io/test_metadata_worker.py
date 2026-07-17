"""Unit tests for MetadataWorker."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import Engine

from musicvault.db.repositories.file_identity_repo import FileIdentityRepository
from musicvault.db.repositories.job_repo import JobRepository
from musicvault.db.repositories.metadata_confidence_repo import MetadataConfidenceRepository
from musicvault.db.repositories.review_repo import ReviewRepository
from musicvault.db.repositories.track_repo import TrackRepository
from musicvault.db.uuid_utils import generate_uuid7
from musicvault.models.entities.job import Job, JobStatus, JobType
from musicvault.models.entities.review_item import ReviewType
from musicvault.models.entities.track import LibraryZone, Track
from musicvault.models.interfaces.metadata import (
    MetadataQuery,
    ProviderFieldResult,
    ProviderResult,
)
from musicvault.models.value_objects.file_identity import FileIdentity
from musicvault.services.job_queue_service import JobQueueService
from musicvault.services.metadata_arbitrator import MetadataArbitrator
from musicvault.services.review_queue_service import ReviewQueueService
from musicvault.workers.io.metadata_worker import MetadataWorker

_NOW = datetime(2026, 7, 15, tzinfo=UTC)


class _StubProvider:
    provider_id = "local_tags"
    priority = 50

    def lookup_by_fingerprint(self, fingerprint: bytes, duration: float) -> ProviderResult | None:
        return None

    def lookup_by_tags(self, query: MetadataQuery) -> ProviderResult | None:
        return ProviderResult(
            provider_id=self.provider_id,
            fields=[
                ProviderFieldResult("title", "Stub Title", 0.95),
                ProviderFieldResult("year", 2001, 0.92),
                ProviderFieldResult("genre", "Jazz", 0.91),
            ],
            overall_confidence=0.91,
            lookup_method="tags",
            priority=self.priority,
        )

    def lookup_by_id(self, external_id: str, id_type: str) -> ProviderResult | None:
        return None

    def search(
        self,
        query: str,
        entity_type: Literal["artist", "album", "recording"],
        limit: int = 10,
    ) -> list[ProviderResult]:
        return []


def _make_track(library_id: UUID, track_id: UUID, **overrides: object) -> Track:
    defaults: dict[str, object] = {
        "id": track_id,
        "library_id": library_id,
        "zone": LibraryZone.INCOMING,
        "file_path": "C:/incoming/track.flac",
        "file_name": "track.flac",
        "file_size": 1024,
        "file_modified": _NOW,
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    defaults.update(overrides)
    return Track(**defaults)  # type: ignore[arg-type]


def test_execute_persists_arbitrated_fields_and_completes_job(
    track_repo: TrackRepository,
    file_identity_repo: FileIdentityRepository,
    job_queue: JobQueueService,
    job_repo: JobRepository,
    review_queue: ReviewQueueService,
    engine: Engine,
    library_id: UUID,
    track_id: UUID,
) -> None:
    track_repo.upsert(_make_track(library_id, track_id))
    file_identity_repo.upsert(
        FileIdentity(
            track_id=track_id,
            content_hash_sha256="a" * 64,
            file_size=1024,
            file_modified=_NOW,
            fingerprint_data=b"fp",
            fingerprint_duration=120.0,
        )
    )
    job_id = job_queue.enqueue(
        JobType.IDENTIFY_METADATA, library_id, {"track_id": str(track_id)}, now=_NOW
    )
    job_repo.update_status(job_id, JobStatus.RUNNING)

    worker = MetadataWorker(
        track_repo,
        file_identity_repo,
        MetadataConfidenceRepository(engine),
        MetadataArbitrator([_StubProvider()], confidence_threshold=0.90),
        job_queue,
        review_queue,
    )
    worker.execute(
        Job(
            id=job_id,
            library_id=library_id,
            job_type=JobType.IDENTIFY_METADATA,
            status=JobStatus.RUNNING,
            payload={"track_id": str(track_id)},
            created_at=_NOW,
        )
    )

    updated = track_repo.get_by_id(track_id)
    assert updated is not None
    assert updated.title == "Stub Title"
    assert updated.year == 2001
    assert updated.genre == "Jazz"
    assert updated.overall_confidence == 0.91
    assert updated.needs_review is False
    conf = MetadataConfidenceRepository(engine).list_for_track(track_id)
    assert {c.field for c in conf} == {"title", "year", "genre"}
    assert job_repo.get(job_id).status is JobStatus.COMPLETED  # type: ignore[union-attr]
    assert review_queue.get_pending(library_id) == []
    duplicate_jobs = [
        job
        for job in job_repo.list_by_status(JobStatus.PENDING)
        if job.job_type is JobType.DETECT_DUPLICATES
    ]
    assert len(duplicate_jobs) == 1
    assert duplicate_jobs[0].payload["track_id"] == str(track_id)
    artwork_jobs = [
        job
        for job in job_repo.list_by_status(JobStatus.PENDING)
        if job.job_type is JobType.FETCH_ARTWORK
    ]
    assert len(artwork_jobs) == 1
    assert artwork_jobs[0].payload["track_id"] == str(track_id)


def test_execute_marks_failed_when_track_missing(
    track_repo: TrackRepository,
    file_identity_repo: FileIdentityRepository,
    job_queue: JobQueueService,
    job_repo: JobRepository,
    review_queue: ReviewQueueService,
    engine: Engine,
    library_id: UUID,
) -> None:
    missing = generate_uuid7()
    job_id = job_queue.enqueue(
        JobType.IDENTIFY_METADATA, library_id, {"track_id": str(missing)}, now=_NOW
    )
    job_repo.update_status(job_id, JobStatus.RUNNING)

    worker = MetadataWorker(
        track_repo,
        file_identity_repo,
        MetadataConfidenceRepository(engine),
        MetadataArbitrator([_StubProvider()]),
        job_queue,
        review_queue,
    )
    worker.execute(
        Job(
            id=job_id,
            library_id=library_id,
            job_type=JobType.IDENTIFY_METADATA,
            status=JobStatus.RUNNING,
            payload={"track_id": str(missing)},
            created_at=_NOW,
        )
    )

    status = job_repo.get(job_id)
    assert status is not None
    assert status.status is JobStatus.RETRY
    assert status.error_message is not None
    assert "not found" in status.error_message


class _AcoustIdStub:
    provider_id = "acoustid"
    priority = 5

    def lookup_by_fingerprint(self, fingerprint: bytes, duration: float) -> ProviderResult | None:
        return ProviderResult(
            provider_id=self.provider_id,
            fields=[
                ProviderFieldResult("acoustid_id", "aid-1", 0.97),
                ProviderFieldResult("acoustid_score", 0.97, 0.97),
                ProviderFieldResult("mb_recording_id", "mbid-1", 0.98),
                ProviderFieldResult("composer", "Composer", 0.91),
                ProviderFieldResult("track_number", 4, 0.91),
            ],
            overall_confidence=0.91,
            lookup_method="fingerprint",
            priority=self.priority,
        )

    def lookup_by_tags(self, query: MetadataQuery) -> ProviderResult | None:
        return None

    def lookup_by_id(self, external_id: str, id_type: str) -> ProviderResult | None:
        return None

    def search(
        self,
        query: str,
        entity_type: Literal["artist", "album", "recording"],
        limit: int = 10,
    ) -> list[ProviderResult]:
        return []


def test_execute_persists_acoustid_fields_on_file_identity(
    track_repo: TrackRepository,
    file_identity_repo: FileIdentityRepository,
    job_queue: JobQueueService,
    job_repo: JobRepository,
    review_queue: ReviewQueueService,
    engine: Engine,
    library_id: UUID,
    track_id: UUID,
) -> None:
    track_repo.upsert(_make_track(library_id, track_id))
    file_identity_repo.upsert(
        FileIdentity(
            track_id=track_id,
            content_hash_sha256="a" * 64,
            file_size=1024,
            file_modified=_NOW,
            fingerprint_data=b"fp",
            fingerprint_duration=90.0,
        )
    )
    job_id = job_queue.enqueue(
        JobType.IDENTIFY_METADATA, library_id, {"track_id": str(track_id)}, now=_NOW
    )
    job_repo.update_status(job_id, JobStatus.RUNNING)

    worker = MetadataWorker(
        track_repo,
        file_identity_repo,
        MetadataConfidenceRepository(engine),
        MetadataArbitrator([_AcoustIdStub()], confidence_threshold=0.90),
        job_queue,
        review_queue,
    )
    worker.execute(
        Job(
            id=job_id,
            library_id=library_id,
            job_type=JobType.IDENTIFY_METADATA,
            status=JobStatus.RUNNING,
            payload={"track_id": str(track_id)},
            created_at=_NOW,
        )
    )

    identity = file_identity_repo.get(track_id)
    assert identity is not None
    assert identity.acoustid_id == "aid-1"
    assert identity.acoustid_score == 0.97
    updated = track_repo.get_by_id(track_id)
    assert updated is not None
    assert updated.mb_recording_id == "mbid-1"
    assert updated.composer == "Composer"
    assert updated.track_number == 4


class _LowConfidenceStub:
    provider_id = "filename_parser"
    priority = 90

    def lookup_by_fingerprint(self, fingerprint: bytes, duration: float) -> ProviderResult | None:
        return None

    def lookup_by_tags(self, query: MetadataQuery) -> ProviderResult | None:
        return ProviderResult(
            provider_id=self.provider_id,
            fields=[ProviderFieldResult("title", "Maybe", 0.40)],
            overall_confidence=0.40,
            lookup_method="filename",
            priority=self.priority,
        )

    def lookup_by_id(self, external_id: str, id_type: str) -> ProviderResult | None:
        return None

    def search(
        self,
        query: str,
        entity_type: Literal["artist", "album", "recording"],
        limit: int = 10,
    ) -> list[ProviderResult]:
        return []


def test_execute_creates_review_item_when_needs_review(
    track_repo: TrackRepository,
    file_identity_repo: FileIdentityRepository,
    job_queue: JobQueueService,
    job_repo: JobRepository,
    review_queue: ReviewQueueService,
    review_repo: ReviewRepository,
    engine: Engine,
    library_id: UUID,
    track_id: UUID,
) -> None:
    track_repo.upsert(_make_track(library_id, track_id))
    job_id = job_queue.enqueue(
        JobType.IDENTIFY_METADATA, library_id, {"track_id": str(track_id)}, now=_NOW
    )
    job_repo.update_status(job_id, JobStatus.RUNNING)

    worker = MetadataWorker(
        track_repo,
        file_identity_repo,
        MetadataConfidenceRepository(engine),
        MetadataArbitrator([_LowConfidenceStub()], confidence_threshold=0.90),
        job_queue,
        review_queue,
    )
    worker.execute(
        Job(
            id=job_id,
            library_id=library_id,
            job_type=JobType.IDENTIFY_METADATA,
            status=JobStatus.RUNNING,
            payload={"track_id": str(track_id)},
            created_at=_NOW,
        )
    )

    updated = track_repo.get_by_id(track_id)
    assert updated is not None
    assert updated.needs_review is True
    pending = review_queue.get_pending(library_id)
    assert len(pending) == 1
    assert pending[0].track_id == track_id
    assert pending[0].review_type is ReviewType.UNKNOWN_ARTIST
    assert review_repo.get(pending[0].id) is not None
