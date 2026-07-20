"""Unit tests for vaultseek.workers.cpu.hash_worker."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from vaultseek.db.repositories.file_identity_repo import FileIdentityRepository
from vaultseek.db.repositories.job_repo import JobRepository
from vaultseek.db.writer import DatabaseWriter
from vaultseek.models.entities.job import JobStatus, JobType
from vaultseek.models.value_objects.file_identity import FileIdentity
from vaultseek.services.job_queue_service import JobQueueService
from vaultseek.workers.cpu.hash_worker import HashWorker, compute_hash

_NOW = datetime(2026, 7, 15, tzinfo=UTC)


def test_compute_hash_returns_the_correct_digest_and_stat(tmp_path: Path) -> None:
    file_path = tmp_path / "track.flac"
    content = b"fake flac bytes" * 1000
    file_path.write_bytes(content)

    result = compute_hash({"track_id": "abc", "file_path": str(file_path)})

    assert result["track_id"] == "abc"
    assert result["content_hash_sha256"] == hashlib.sha256(content).hexdigest()
    assert result["file_size"] == len(content)
    assert datetime.fromisoformat(result["file_modified"]) is not None


def test_compute_hash_returns_an_error_for_a_missing_file(tmp_path: Path) -> None:
    result = compute_hash({"track_id": "abc", "file_path": str(tmp_path / "missing.flac")})

    assert result["track_id"] == "abc"
    assert "error" in result


def test_compute_hash_streams_in_chunks_for_large_files(tmp_path: Path) -> None:
    """Not just a small in-memory read — must handle a file bigger than
    one chunk without loading it all into memory in one call."""
    from vaultseek.workers.cpu.hash_worker import _CHUNK_SIZE

    file_path = tmp_path / "big.flac"
    content = b"x" * (_CHUNK_SIZE * 2 + 123)
    file_path.write_bytes(content)

    result = compute_hash({"track_id": "abc", "file_path": str(file_path)})

    assert result["content_hash_sha256"] == hashlib.sha256(content).hexdigest()
    assert result["file_size"] == len(content)


def test_handle_result_marks_the_job_failed_on_error(
    job_repo: JobRepository,
    job_queue: JobQueueService,
    file_identity_repo: FileIdentityRepository,
    database_writer: DatabaseWriter,
    library_id: UUID,
    track_id: UUID,
) -> None:
    worker = HashWorker(file_identity_repo, database_writer, job_queue)
    job_id = job_queue.enqueue(
        JobType.HASH_FILE,
        library_id,
        {"track_id": str(track_id), "file_path": "C:/library/track.flac"},
        now=_NOW,
    )
    job = job_repo.get(job_id)
    assert job is not None

    worker.handle_result(job, {"track_id": str(track_id), "error": "permission denied"})

    updated = job_repo.get(job_id)
    assert updated is not None
    assert updated.status is JobStatus.RETRY
    assert updated.error_message == "permission denied"


def test_handle_result_for_a_new_track_persists_identity_and_chains_to_fingerprint(
    job_repo: JobRepository,
    job_queue: JobQueueService,
    file_identity_repo: FileIdentityRepository,
    database_writer: DatabaseWriter,
    library_id: UUID,
    track_id: UUID,
) -> None:
    worker = HashWorker(file_identity_repo, database_writer, job_queue)
    job_id = job_queue.enqueue(
        JobType.HASH_FILE,
        library_id,
        {"track_id": str(track_id), "file_path": "C:/library/track.flac"},
        now=_NOW,
    )
    job = job_repo.get(job_id)
    assert job is not None

    worker.handle_result(
        job,
        {
            "track_id": str(track_id),
            "content_hash_sha256": "a" * 64,
            "file_size": 2048,
            "file_modified": _NOW.isoformat(),
        },
    )
    database_writer.stop()  # deterministic flush before asserting

    identity = file_identity_repo.get(track_id)
    assert identity is not None
    assert identity.content_hash_sha256 == "a" * 64

    fingerprint_jobs = job_repo.list_by_status(JobStatus.PENDING, library_id=library_id)
    assert any(j.job_type is JobType.FINGERPRINT_FILE for j in fingerprint_jobs)
    assert job_repo.get(job_id).status is JobStatus.COMPLETED  # type: ignore[union-attr]


def test_handle_result_preserves_existing_fingerprint_when_hash_unchanged(
    job_repo: JobRepository,
    job_queue: JobQueueService,
    file_identity_repo: FileIdentityRepository,
    database_writer: DatabaseWriter,
    library_id: UUID,
    track_id: UUID,
) -> None:
    file_identity_repo.upsert(
        FileIdentity(
            track_id=track_id,
            content_hash_sha256="a" * 64,
            file_size=1024,
            file_modified=_NOW,
            fingerprint_data=b"chromaprint-bytes",
            fingerprint_duration=180.0,
            fingerprint_hash="fp" * 32,
        )
    )
    worker = HashWorker(file_identity_repo, database_writer, job_queue)
    job_id = job_queue.enqueue(
        JobType.HASH_FILE,
        library_id,
        {"track_id": str(track_id), "file_path": "C:/library/track.flac"},
        now=_NOW,
    )
    job = job_repo.get(job_id)
    assert job is not None

    worker.handle_result(
        job,
        {
            "track_id": str(track_id),
            "content_hash_sha256": "a" * 64,
            "file_size": 1024,
            "file_modified": _NOW.isoformat(),
        },
    )
    database_writer.stop()

    identity = file_identity_repo.get(track_id)
    assert identity is not None
    assert identity.fingerprint_data == b"chromaprint-bytes"
    assert identity.fingerprint_duration == 180.0
    assert identity.fingerprint_hash == "fp" * 32


def test_handle_result_includes_file_path_on_fingerprint_jobs(
    job_repo: JobRepository,
    job_queue: JobQueueService,
    file_identity_repo: FileIdentityRepository,
    database_writer: DatabaseWriter,
    library_id: UUID,
    track_id: UUID,
) -> None:
    worker = HashWorker(file_identity_repo, database_writer, job_queue)
    job_id = job_queue.enqueue(
        JobType.HASH_FILE,
        library_id,
        {"track_id": str(track_id), "file_path": "C:/library/song.flac"},
        now=_NOW,
    )
    job = job_repo.get(job_id)
    assert job is not None

    worker.handle_result(
        job,
        {
            "track_id": str(track_id),
            "content_hash_sha256": "c" * 64,
            "file_size": 99,
            "file_modified": _NOW.isoformat(),
        },
    )

    fingerprint_jobs = [
        j
        for j in job_repo.list_by_status(JobStatus.PENDING, library_id=library_id)
        if j.job_type is JobType.FINGERPRINT_FILE
    ]
    assert len(fingerprint_jobs) == 1
    assert fingerprint_jobs[0].payload == {
        "track_id": str(track_id),
        "file_path": "C:/library/song.flac",
    }


def test_handle_result_skips_fingerprint_when_content_hash_is_unchanged(
    job_repo: JobRepository,
    job_queue: JobQueueService,
    file_identity_repo: FileIdentityRepository,
    database_writer: DatabaseWriter,
    library_id: UUID,
    track_id: UUID,
) -> None:
    file_identity_repo.upsert(
        FileIdentity(
            track_id=track_id,
            content_hash_sha256="a" * 64,
            file_size=1024,
            file_modified=_NOW,
        )
    )
    worker = HashWorker(file_identity_repo, database_writer, job_queue)
    job_id = job_queue.enqueue(
        JobType.HASH_FILE,
        library_id,
        {"track_id": str(track_id), "file_path": "C:/library/track.flac"},
        now=_NOW,
    )
    job = job_repo.get(job_id)
    assert job is not None

    worker.handle_result(
        job,
        {
            "track_id": str(track_id),
            "content_hash_sha256": "a" * 64,  # unchanged
            "file_size": 1024,
            "file_modified": _NOW.isoformat(),
        },
    )
    database_writer.stop()

    fingerprint_jobs = job_repo.list_by_status(JobStatus.PENDING, library_id=library_id)
    assert not any(j.job_type is JobType.FINGERPRINT_FILE for j in fingerprint_jobs)
    assert job_repo.get(job_id).status is JobStatus.COMPLETED  # type: ignore[union-attr]


def test_handle_result_chains_to_fingerprint_when_content_hash_changed(
    job_repo: JobRepository,
    job_queue: JobQueueService,
    file_identity_repo: FileIdentityRepository,
    database_writer: DatabaseWriter,
    library_id: UUID,
    track_id: UUID,
) -> None:
    file_identity_repo.upsert(
        FileIdentity(
            track_id=track_id,
            content_hash_sha256="a" * 64,
            file_size=1024,
            file_modified=_NOW,
        )
    )
    worker = HashWorker(file_identity_repo, database_writer, job_queue)
    job_id = job_queue.enqueue(
        JobType.HASH_FILE,
        library_id,
        {"track_id": str(track_id), "file_path": "C:/library/track.flac"},
        now=_NOW,
    )
    job = job_repo.get(job_id)
    assert job is not None

    worker.handle_result(
        job,
        {
            "track_id": str(track_id),
            "content_hash_sha256": "b" * 64,  # changed
            "file_size": 2048,
            "file_modified": _NOW.isoformat(),
        },
    )
    database_writer.stop()

    fingerprint_jobs = job_repo.list_by_status(JobStatus.PENDING, library_id=library_id)
    assert any(j.job_type is JobType.FINGERPRINT_FILE for j in fingerprint_jobs)
