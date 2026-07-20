"""Unit tests for vaultseek.workers.cpu.fingerprint_worker."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

from vaultseek.db.repositories.file_identity_repo import FileIdentityRepository
from vaultseek.db.repositories.job_repo import JobRepository
from vaultseek.db.writer import DatabaseWriter
from vaultseek.models.entities.job import JobStatus, JobType
from vaultseek.models.interfaces.fingerprint import FingerprintResult
from vaultseek.models.value_objects.file_identity import FileIdentity
from vaultseek.services.job_queue_service import JobQueueService
from vaultseek.workers.cpu.fingerprint_worker import FingerprintWorker, compute_fingerprint

_NOW = datetime(2026, 7, 15, tzinfo=UTC)


def test_compute_fingerprint_returns_chromaprint_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audio = tmp_path / "track.flac"
    audio.write_bytes(b"fake")

    def _fake_generate(path: Path) -> FingerprintResult:
        assert path == audio
        return FingerprintResult(
            duration_seconds=123.4,
            fingerprint_data=b"fp-bytes",
            fingerprint_hash="ab" * 32,
        )

    monkeypatch.setattr(
        "vaultseek.workers.cpu.fingerprint_worker.generate_chromaprint", _fake_generate
    )

    result = compute_fingerprint({"track_id": "abc", "file_path": str(audio)})

    assert result == {
        "track_id": "abc",
        "fingerprint_data": b"fp-bytes",
        "fingerprint_duration": 123.4,
        "fingerprint_hash": "ab" * 32,
    }


def test_compute_fingerprint_returns_an_error_when_chromaprint_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audio = tmp_path / "track.flac"
    audio.write_bytes(b"fake")

    def _boom(_path: Path) -> FingerprintResult:
        raise RuntimeError("fpcalc not found")

    monkeypatch.setattr("vaultseek.workers.cpu.fingerprint_worker.generate_chromaprint", _boom)

    result = compute_fingerprint({"track_id": "abc", "file_path": str(audio)})

    assert result["track_id"] == "abc"
    assert "fpcalc not found" in result["error"]


def test_handle_result_marks_the_job_failed_on_error(
    job_repo: JobRepository,
    job_queue: JobQueueService,
    file_identity_repo: FileIdentityRepository,
    database_writer: DatabaseWriter,
    library_id: UUID,
    track_id: UUID,
) -> None:
    worker = FingerprintWorker(file_identity_repo, database_writer, job_queue)
    job_id = job_queue.enqueue(
        JobType.FINGERPRINT_FILE,
        library_id,
        {"track_id": str(track_id), "file_path": "C:/x.flac"},
        now=_NOW,
    )
    job = job_repo.get(job_id)
    assert job is not None

    worker.handle_result(job, {"track_id": str(track_id), "error": "no backend"})

    updated = job_repo.get(job_id)
    assert updated is not None
    assert updated.status is JobStatus.RETRY
    assert updated.error_message == "no backend"


def test_handle_result_fails_when_file_identity_is_missing(
    job_repo: JobRepository,
    job_queue: JobQueueService,
    file_identity_repo: FileIdentityRepository,
    database_writer: DatabaseWriter,
    library_id: UUID,
    track_id: UUID,
) -> None:
    worker = FingerprintWorker(file_identity_repo, database_writer, job_queue)
    job_id = job_queue.enqueue(
        JobType.FINGERPRINT_FILE,
        library_id,
        {"track_id": str(track_id), "file_path": "C:/x.flac"},
        now=_NOW,
    )
    job = job_repo.get(job_id)
    assert job is not None

    worker.handle_result(
        job,
        {
            "track_id": str(track_id),
            "fingerprint_data": b"fp",
            "fingerprint_duration": 1.0,
            "fingerprint_hash": "aa" * 32,
        },
    )

    updated = job_repo.get(job_id)
    assert updated is not None
    assert updated.status is JobStatus.RETRY
    assert "No file_identity row" in (updated.error_message or "")


def test_handle_result_persists_fingerprint_and_chains_to_identify_metadata(
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
            hash_computed_at=_NOW,
        )
    )
    worker = FingerprintWorker(file_identity_repo, database_writer, job_queue)
    job_id = job_queue.enqueue(
        JobType.FINGERPRINT_FILE,
        library_id,
        {"track_id": str(track_id), "file_path": "C:/x.flac"},
        now=_NOW,
    )
    job = job_repo.get(job_id)
    assert job is not None

    worker.handle_result(
        job,
        {
            "track_id": str(track_id),
            "fingerprint_data": b"chromaprint",
            "fingerprint_duration": 210.5,
            "fingerprint_hash": "cd" * 32,
        },
    )
    database_writer.stop()

    identity = file_identity_repo.get(track_id)
    assert identity is not None
    assert identity.fingerprint_data == b"chromaprint"
    assert identity.fingerprint_duration == 210.5
    assert identity.fingerprint_hash == "cd" * 32
    assert identity.content_hash_sha256 == "a" * 64  # hash fields preserved
    assert identity.fingerprint_computed_at is not None

    metadata_jobs = [
        j
        for j in job_repo.list_by_status(JobStatus.PENDING, library_id=library_id)
        if j.job_type is JobType.IDENTIFY_METADATA
    ]
    assert len(metadata_jobs) == 1
    assert metadata_jobs[0].payload == {"track_id": str(track_id)}
    assert job_repo.get(job_id).status is JobStatus.COMPLETED  # type: ignore[union-attr]


def test_already_fingerprinted_and_complete_without_recompute(
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
            fingerprint_data=b"existing",
            fingerprint_hash="ee" * 32,
        )
    )
    worker = FingerprintWorker(file_identity_repo, database_writer, job_queue)
    job_id = job_queue.enqueue(
        JobType.FINGERPRINT_FILE,
        library_id,
        {"track_id": str(track_id), "file_path": "C:/x.flac"},
        now=_NOW,
    )
    job = job_repo.get(job_id)
    assert job is not None

    assert worker.already_fingerprinted(job) is True
    worker.complete_without_recompute(job)

    assert job_repo.get(job_id).status is JobStatus.COMPLETED  # type: ignore[union-attr]
    assert any(
        j.job_type is JobType.IDENTIFY_METADATA
        for j in job_repo.list_by_status(JobStatus.PENDING, library_id=library_id)
    )


def test_already_fingerprinted_is_false_without_fingerprint_data(
    job_repo: JobRepository,
    file_identity_repo: FileIdentityRepository,
    database_writer: DatabaseWriter,
    job_queue: JobQueueService,
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
    worker = FingerprintWorker(file_identity_repo, database_writer, job_queue)
    job_id = job_queue.enqueue(
        JobType.FINGERPRINT_FILE,
        library_id,
        {"track_id": str(track_id), "file_path": "C:/x.flac"},
        now=_NOW,
    )
    job = job_repo.get(job_id)
    assert job is not None
    assert worker.already_fingerprinted(job) is False
