"""Unit tests for library processing reset."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4, uuid7

from vaultseek.db.repositories.job_repo import JobRepository
from vaultseek.db.repositories.library_repo import LibraryRepository
from vaultseek.db.repositories.review_repo import ReviewRepository
from vaultseek.db.repositories.track_repo import TrackRepository
from vaultseek.models.entities.job import Job, JobStatus, JobType
from vaultseek.models.entities.library import Library
from vaultseek.models.entities.review_item import ReviewItem, ReviewStatus, ReviewType
from vaultseek.models.entities.track import LibraryZone, Track
from vaultseek.services.library_reset import reset_library_processing


def _library() -> Library:
    now = datetime.now(UTC)
    return Library(
        id=uuid7(),
        name="Test",
        incoming_path="/in",
        staging_path="/st",
        library_path="/lib",
        archive_path="/ar",
        created_at=now,
        updated_at=now,
    )


def test_reset_queues_keeps_tracks(engine) -> None:
    lib = _library()
    LibraryRepository(engine).upsert(lib)
    track = Track(
        id=uuid7(),
        library_id=lib.id,
        zone=LibraryZone.INCOMING,
        file_path=f"/in/{uuid4()}.flac",
        file_name="a.flac",
        file_size=10,
        file_modified=datetime.now(UTC),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    TrackRepository(engine).upsert(track)
    JobRepository(engine).create(
        Job(
            id=uuid7(),
            library_id=lib.id,
            job_type=JobType.HASH_FILE,
            status=JobStatus.FAILED,
            payload={"path": track.file_path},
            created_at=datetime.now(UTC),
            error_message="boom",
        )
    )
    ReviewRepository(engine).create(
        ReviewItem(
            id=uuid7(),
            library_id=lib.id,
            review_type=ReviewType.METADATA_CONFLICT,
            status=ReviewStatus.PENDING,
            title="Check",
            created_at=datetime.now(UTC),
            track_id=track.id,
        )
    )

    result = reset_library_processing(engine, lib.id, clear_catalog=False)

    assert result.jobs_deleted == 1
    assert result.reviews_deleted == 1
    assert result.tracks_deleted == 0
    assert TrackRepository(engine).get_by_id(track.id) is not None
    assert JobRepository(engine).count_by_status(lib.id) == {}


def test_reset_catalog_removes_tracks(engine) -> None:
    lib = _library()
    LibraryRepository(engine).upsert(lib)
    track = Track(
        id=uuid7(),
        library_id=lib.id,
        zone=LibraryZone.STAGING,
        file_path=f"/st/{uuid4()}.flac",
        file_name="b.flac",
        file_size=10,
        file_modified=datetime.now(UTC),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    TrackRepository(engine).upsert(track)

    result = reset_library_processing(engine, lib.id, clear_catalog=True)

    assert result.tracks_deleted == 1
    assert TrackRepository(engine).get_by_id(track.id) is None
    assert LibraryRepository(engine).get(lib.id) is not None
