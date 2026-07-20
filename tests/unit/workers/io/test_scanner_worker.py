"""Unit tests for vaultseek.workers.io.scanner_worker.ScannerWorker."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

import vaultseek.workers.io.scanner_worker as scanner_worker_module
from vaultseek.db.repositories.file_identity_repo import FileIdentityRepository
from vaultseek.db.repositories.job_repo import JobRepository
from vaultseek.db.repositories.track_repo import TrackRepository
from vaultseek.db.uuid_utils import generate_uuid7
from vaultseek.db.writer import DatabaseWriter
from vaultseek.models.entities.job import JobStatus, JobType
from vaultseek.models.entities.track import LibraryZone, Track
from vaultseek.models.value_objects.file_identity import FileIdentity
from vaultseek.services.job_queue_service import JobQueueService
from vaultseek.workers.io.scanner_worker import ScannerWorker, _iter_audio_files

_NOW = datetime(2026, 7, 15, tzinfo=UTC)


def _make_worker(
    track_repo: TrackRepository,
    file_identity_repo: FileIdentityRepository,
    database_writer: DatabaseWriter,
    job_queue: JobQueueService,
) -> ScannerWorker:
    return ScannerWorker(track_repo, file_identity_repo, database_writer, job_queue)


def test_iter_audio_files_only_yields_known_audio_extensions(tmp_path: Path) -> None:
    (tmp_path / "song.flac").write_bytes(b"x")
    (tmp_path / "song.mp3").write_bytes(b"x")
    (tmp_path / "cover.jpg").write_bytes(b"x")
    (tmp_path / "readme.txt").write_text("x")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "nested.flac").write_bytes(b"x")

    found = {path.name for path in _iter_audio_files(tmp_path)}

    assert found == {"song.flac", "song.mp3", "nested.flac"}


def test_execute_marks_the_job_failed_when_the_directory_does_not_exist(
    job_repo: JobRepository,
    job_queue: JobQueueService,
    track_repo: TrackRepository,
    file_identity_repo: FileIdentityRepository,
    database_writer: DatabaseWriter,
    library_id: UUID,
    tmp_path: Path,
) -> None:
    worker = _make_worker(track_repo, file_identity_repo, database_writer, job_queue)
    job_id = job_queue.enqueue(
        JobType.SCAN_DIRECTORY,
        library_id,
        {"directory": str(tmp_path / "does-not-exist"), "zone": "incoming"},
        now=_NOW,
    )
    job = job_repo.get(job_id)
    assert job is not None

    worker.execute(job)

    updated = job_repo.get(job_id)
    assert updated is not None
    assert updated.status is JobStatus.RETRY  # first failure, attempts remain
    assert updated.error_message is not None


def test_execute_marks_the_job_failed_when_listing_the_directory_raises(
    job_repo: JobRepository,
    job_queue: JobQueueService,
    track_repo: TrackRepository,
    file_identity_repo: FileIdentityRepository,
    database_writer: DatabaseWriter,
    library_id: UUID,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`directory.is_dir()` can pass but a later `PermissionError` while
    actually listing its contents is still possible — exercised here via
    monkeypatching since reliably revoking read permission on a real
    directory isn't portable across platforms."""

    def _raise(_directory: Path) -> Iterator[Path]:
        raise PermissionError("access denied")
        yield  # pragma: no cover - makes this a generator, never reached

    monkeypatch.setattr(scanner_worker_module, "_iter_audio_files", _raise)
    worker = _make_worker(track_repo, file_identity_repo, database_writer, job_queue)
    job_id = job_queue.enqueue(
        JobType.SCAN_DIRECTORY,
        library_id,
        {"directory": str(tmp_path), "zone": "incoming"},
        now=_NOW,
    )
    job = job_repo.get(job_id)
    assert job is not None

    worker.execute(job)

    updated = job_repo.get(job_id)
    assert updated is not None
    assert updated.status is JobStatus.RETRY
    assert updated.error_message is not None


def test_execute_completes_immediately_for_an_empty_directory(
    job_repo: JobRepository,
    job_queue: JobQueueService,
    track_repo: TrackRepository,
    file_identity_repo: FileIdentityRepository,
    database_writer: DatabaseWriter,
    library_id: UUID,
    tmp_path: Path,
) -> None:
    worker = _make_worker(track_repo, file_identity_repo, database_writer, job_queue)
    job_id = job_queue.enqueue(
        JobType.SCAN_DIRECTORY,
        library_id,
        {"directory": str(tmp_path), "zone": "incoming"},
        now=_NOW,
    )
    job = job_repo.get(job_id)
    assert job is not None

    worker.execute(job)

    assert job_repo.get(job_id).status is JobStatus.COMPLETED  # type: ignore[union-attr]


def test_execute_discovers_a_new_file_upserts_track_and_enqueues_hash(
    job_repo: JobRepository,
    job_queue: JobQueueService,
    track_repo: TrackRepository,
    file_identity_repo: FileIdentityRepository,
    database_writer: DatabaseWriter,
    library_id: UUID,
    tmp_path: Path,
) -> None:
    audio_file = tmp_path / "track.flac"
    audio_file.write_bytes(b"fake flac content")
    worker = _make_worker(track_repo, file_identity_repo, database_writer, job_queue)
    job_id = job_queue.enqueue(
        JobType.SCAN_DIRECTORY,
        library_id,
        {"directory": str(tmp_path), "zone": "incoming"},
        now=_NOW,
    )
    job = job_repo.get(job_id)
    assert job is not None

    worker.execute(job)
    database_writer.stop()

    track = track_repo.get_by_path(str(audio_file))
    assert track is not None
    assert track.zone is LibraryZone.INCOMING
    assert track.file_size == audio_file.stat().st_size

    hash_jobs = job_repo.list_by_status(JobStatus.PENDING, library_id=library_id)
    matching = [j for j in hash_jobs if j.job_type is JobType.HASH_FILE]
    assert len(matching) == 1
    assert matching[0].payload["track_id"] == str(track.id)
    assert matching[0].payload["file_path"] == str(audio_file)
    assert job_repo.get(job_id).status is JobStatus.COMPLETED  # type: ignore[union-attr]


def test_execute_skips_an_unchanged_file_entirely(
    job_repo: JobRepository,
    job_queue: JobQueueService,
    track_repo: TrackRepository,
    file_identity_repo: FileIdentityRepository,
    database_writer: DatabaseWriter,
    library_id: UUID,
    tmp_path: Path,
) -> None:
    audio_file = tmp_path / "track.flac"
    audio_file.write_bytes(b"fake flac content")
    stat = audio_file.stat()
    file_modified = datetime.fromtimestamp(stat.st_mtime, tz=UTC)

    track_id = generate_uuid7()
    track_repo.upsert(
        Track(
            id=track_id,
            library_id=library_id,
            zone=LibraryZone.INCOMING,
            file_path=str(audio_file),
            file_name=audio_file.name,
            file_size=stat.st_size,
            file_modified=file_modified,
            created_at=_NOW,
            updated_at=_NOW,
        )
    )
    file_identity_repo.upsert(
        FileIdentity(
            track_id=track_id,
            content_hash_sha256="a" * 64,
            file_size=stat.st_size,
            file_modified=file_modified,
        )
    )

    worker = _make_worker(track_repo, file_identity_repo, database_writer, job_queue)
    job_id = job_queue.enqueue(
        JobType.SCAN_DIRECTORY,
        library_id,
        {"directory": str(tmp_path), "zone": "incoming"},
        now=_NOW,
    )
    job = job_repo.get(job_id)
    assert job is not None

    worker.execute(job)
    database_writer.stop()

    hash_jobs = job_repo.list_by_status(JobStatus.PENDING, library_id=library_id)
    assert not any(j.job_type is JobType.HASH_FILE for j in hash_jobs)
    assert job_repo.get(job_id).status is JobStatus.COMPLETED  # type: ignore[union-attr]


def test_execute_rescans_a_changed_known_file_and_preserves_its_metadata(
    job_repo: JobRepository,
    job_queue: JobQueueService,
    track_repo: TrackRepository,
    file_identity_repo: FileIdentityRepository,
    database_writer: DatabaseWriter,
    library_id: UUID,
    tmp_path: Path,
) -> None:
    audio_file = tmp_path / "track.flac"
    audio_file.write_bytes(b"original content")
    track_id = generate_uuid7()
    track_repo.upsert(
        Track(
            id=track_id,
            library_id=library_id,
            zone=LibraryZone.INCOMING,
            file_path=str(audio_file),
            file_name=audio_file.name,
            file_size=1,  # deliberately stale, forces a "changed" detection
            file_modified=_NOW,
            created_at=_NOW,
            updated_at=_NOW,
            title="Previously Arbitrated Title",
        )
    )

    worker = _make_worker(track_repo, file_identity_repo, database_writer, job_queue)
    job_id = job_queue.enqueue(
        JobType.SCAN_DIRECTORY,
        library_id,
        {"directory": str(tmp_path), "zone": "incoming"},
        now=_NOW,
    )
    job = job_repo.get(job_id)
    assert job is not None

    worker.execute(job)
    database_writer.stop()

    track = track_repo.get_by_id(track_id)
    assert track is not None
    assert track.title == "Previously Arbitrated Title"  # preserved, not wiped
    assert track.file_size == audio_file.stat().st_size  # refreshed

    hash_jobs = job_repo.list_by_status(JobStatus.PENDING, library_id=library_id)
    assert any(j.job_type is JobType.HASH_FILE for j in hash_jobs)


def test_process_file_logs_and_continues_when_a_file_disappears_mid_scan(
    job_repo: JobRepository,
    job_queue: JobQueueService,
    track_repo: TrackRepository,
    file_identity_repo: FileIdentityRepository,
    database_writer: DatabaseWriter,
    library_id: UUID,
    tmp_path: Path,
) -> None:
    """Simulates a TOCTOU race (deleted between listing and stat()) by
    calling the per-file step directly with a path that was never on
    disk — the only reliable way to exercise this branch deterministically.
    """
    worker = _make_worker(track_repo, file_identity_repo, database_writer, job_queue)
    job_id = job_queue.enqueue(
        JobType.SCAN_DIRECTORY,
        library_id,
        {"directory": str(tmp_path), "zone": "incoming"},
        now=_NOW,
    )
    job = job_repo.get(job_id)
    assert job is not None

    worker._process_file(
        job, tmp_path / "vanished.flac", LibraryZone.INCOMING, force=False
    )  # noqa: SLF001

    assert track_repo.get_by_path(str(tmp_path / "vanished.flac")) is None


def test_execute_force_requeues_unchanged_files(
    job_repo: JobRepository,
    job_queue: JobQueueService,
    track_repo: TrackRepository,
    file_identity_repo: FileIdentityRepository,
    database_writer: DatabaseWriter,
    library_id: UUID,
    tmp_path: Path,
) -> None:
    audio_file = tmp_path / "track.flac"
    audio_file.write_bytes(b"fake flac content")
    stat = audio_file.stat()
    file_modified = datetime.fromtimestamp(stat.st_mtime, tz=UTC)

    track_id = generate_uuid7()
    track_repo.upsert(
        Track(
            id=track_id,
            library_id=library_id,
            zone=LibraryZone.INCOMING,
            file_path=str(audio_file),
            file_name=audio_file.name,
            file_size=stat.st_size,
            file_modified=file_modified,
            created_at=_NOW,
            updated_at=_NOW,
        )
    )
    file_identity_repo.upsert(
        FileIdentity(
            track_id=track_id,
            content_hash_sha256="a" * 64,
            file_size=stat.st_size,
            file_modified=file_modified,
        )
    )

    worker = _make_worker(track_repo, file_identity_repo, database_writer, job_queue)
    job_id = job_queue.enqueue(
        JobType.SCAN_DIRECTORY,
        library_id,
        {"directory": str(tmp_path), "zone": "incoming", "force": True},
        now=_NOW,
    )
    job = job_repo.get(job_id)
    assert job is not None

    worker.execute(job)
    database_writer.stop()

    hash_jobs = [
        j
        for j in job_repo.list_by_status(JobStatus.PENDING, library_id=library_id)
        if j.job_type is JobType.HASH_FILE
    ]
    assert len(hash_jobs) == 1
    assert hash_jobs[0].payload.get("force") is True
    completed = job_repo.get(job_id)
    assert completed is not None
    assert completed.status is JobStatus.COMPLETED
    assert completed.error_message is not None
    assert "force" in completed.error_message
    assert "1 queued" in completed.error_message
    assert completed.payload.get("files_skipped") == 0
    assert completed.payload.get("files_queued") == 1


def test_execute_records_skip_summary_for_unchanged_files(
    job_repo: JobRepository,
    job_queue: JobQueueService,
    track_repo: TrackRepository,
    file_identity_repo: FileIdentityRepository,
    database_writer: DatabaseWriter,
    library_id: UUID,
    tmp_path: Path,
) -> None:
    audio_file = tmp_path / "track.flac"
    audio_file.write_bytes(b"fake flac content")
    stat = audio_file.stat()
    file_modified = datetime.fromtimestamp(stat.st_mtime, tz=UTC)
    track_id = generate_uuid7()
    track_repo.upsert(
        Track(
            id=track_id,
            library_id=library_id,
            zone=LibraryZone.INCOMING,
            file_path=str(audio_file),
            file_name=audio_file.name,
            file_size=stat.st_size,
            file_modified=file_modified,
            created_at=_NOW,
            updated_at=_NOW,
        )
    )
    file_identity_repo.upsert(
        FileIdentity(
            track_id=track_id,
            content_hash_sha256="a" * 64,
            file_size=stat.st_size,
            file_modified=file_modified,
        )
    )
    worker = _make_worker(track_repo, file_identity_repo, database_writer, job_queue)
    job_id = job_queue.enqueue(
        JobType.SCAN_DIRECTORY,
        library_id,
        {"directory": str(tmp_path), "zone": "incoming"},
        now=_NOW,
    )
    job = job_repo.get(job_id)
    assert job is not None
    worker.execute(job)

    completed = job_repo.get(job_id)
    assert completed is not None
    assert completed.status is JobStatus.COMPLETED
    assert "1 unchanged skipped" in (completed.error_message or "")
    assert completed.payload.get("files_queued") == 0
    assert completed.payload.get("files_skipped") == 1
