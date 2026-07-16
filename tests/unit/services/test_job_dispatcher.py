"""Unit tests for musicvault.services.job_dispatcher.JobDispatcher."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from concurrent.futures import Future
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import Engine

from musicvault.db.repositories.file_identity_repo import FileIdentityRepository
from musicvault.db.repositories.job_repo import JobRepository
from musicvault.db.repositories.metadata_confidence_repo import MetadataConfidenceRepository
from musicvault.db.repositories.track_repo import TrackRepository
from musicvault.db.writer import DatabaseWriter
from musicvault.models.entities.job import JobStatus, JobType
from musicvault.plugins.builtin.filename_parser import FilenameParserProvider
from musicvault.services.job_dispatcher import JobDispatcher
from musicvault.services.job_queue_service import JobQueueService
from musicvault.services.metadata_arbitrator import MetadataArbitrator
from musicvault.services.review_queue_service import ReviewQueueService
from musicvault.workers.cpu.fingerprint_worker import FingerprintWorker
from musicvault.workers.cpu.hash_worker import HashWorker
from musicvault.workers.io.metadata_worker import MetadataWorker
from musicvault.workers.io.scanner_worker import ScannerWorker

_NOW = datetime(2026, 7, 15, tzinfo=UTC)
_POLL_TIMEOUT_SECONDS = 5.0


class _SynchronousExecutor:
    """Test stand-in for `ProcessPoolExecutor`.

    Runs each submitted callable in the caller's thread so these unit tests
    exercise the dispatcher's submit/done-callback wiring without spawning
    real worker processes — which is slow and flaky on GitHub Actions
    Windows runners. :func:`~musicvault.workers.cpu.hash_worker.compute_hash`
    and :func:`~musicvault.workers.cpu.fingerprint_worker.compute_fingerprint`
    are covered separately in their own worker test modules.
    """

    def submit(self, fn: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Future[Any]:
        future: Future[Any] = Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except Exception as exc:
            future.set_exception(exc)
        return future

    def shutdown(self, *, wait: bool = True, cancel_futures: bool = False) -> None:
        pass


@pytest.fixture
def dispatcher(
    job_queue: JobQueueService,
    track_repo: TrackRepository,
    file_identity_repo: FileIdentityRepository,
    database_writer: DatabaseWriter,
    review_queue: ReviewQueueService,
    engine: Engine,
) -> Iterator[JobDispatcher]:
    scanner = ScannerWorker(track_repo, file_identity_repo, database_writer, job_queue)
    hasher = HashWorker(file_identity_repo, database_writer, job_queue)
    fingerprinter = FingerprintWorker(file_identity_repo, database_writer, job_queue)
    arbitrator = MetadataArbitrator([FilenameParserProvider()], confidence_threshold=0.90)
    metadata = MetadataWorker(
        track_repo,
        file_identity_repo,
        MetadataConfidenceRepository(engine),
        arbitrator,
        job_queue,
        review_queue,
    )
    disp = JobDispatcher(
        job_queue,
        scanner,
        hasher,
        fingerprinter,
        metadata,
        scanner_threads=1,
        hash_processes=1,
        metadata_threads=1,
        claim_batch_size=10,
        poll_interval_seconds=0.05,
    )
    # Swap out the real process pool before any work is submitted.
    real_cpu_pool = disp._cpu_pool  # noqa: SLF001
    disp._cpu_pool = _SynchronousExecutor()  # type: ignore[assignment]  # noqa: SLF001
    real_cpu_pool.shutdown(wait=False, cancel_futures=True)
    yield disp
    disp.stop()


def _wait_until(predicate: Callable[[], bool], *, timeout: float = _POLL_TIMEOUT_SECONDS) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def test_recover_delegates_to_the_job_queue(
    dispatcher: JobDispatcher,
    job_queue: JobQueueService,
    job_repo: JobRepository,
    library_id: UUID,
) -> None:
    job_id = job_queue.enqueue(JobType.HASH_FILE, library_id, {}, now=_NOW)
    job_repo.update_status(job_id, JobStatus.RUNNING)

    count = dispatcher.recover()

    assert count == 1
    assert job_repo.get(job_id).status is JobStatus.RETRY  # type: ignore[union-attr]


def test_run_cycle_dispatches_a_scan_directory_job_via_the_thread_pool(
    dispatcher: JobDispatcher,
    job_queue: JobQueueService,
    job_repo: JobRepository,
    library_id: UUID,
    tmp_path: Path,
) -> None:
    audio_file = tmp_path / "track.flac"
    audio_file.write_bytes(b"content")
    job_id = job_queue.enqueue(
        JobType.SCAN_DIRECTORY,
        library_id,
        {"directory": str(tmp_path), "zone": "incoming"},
        now=_NOW,
    )

    futures = dispatcher.run_cycle()
    assert len(futures) == 1
    futures[0].result(timeout=_POLL_TIMEOUT_SECONDS)

    job = job_repo.get(job_id)
    assert job is not None
    assert job.status is JobStatus.COMPLETED


def test_run_cycle_dispatches_a_hash_file_job_and_runs_its_done_callback(
    dispatcher: JobDispatcher,
    job_queue: JobQueueService,
    job_repo: JobRepository,
    library_id: UUID,
    track_id: UUID,
    tmp_path: Path,
) -> None:
    audio_file = tmp_path / "track.flac"
    audio_file.write_bytes(b"some content")
    job_id = job_queue.enqueue(
        JobType.HASH_FILE,
        library_id,
        {"track_id": str(track_id), "file_path": str(audio_file)},
        now=_NOW,
    )

    futures = dispatcher.run_cycle()
    # Sync executor runs hash immediately and may enqueue+claim fingerprint
    # in the same cycle — wait on every future returned.
    assert len(futures) >= 1
    for future in futures:
        future.result(timeout=_POLL_TIMEOUT_SECONDS)

    job = job_repo.get(job_id)
    assert job is not None
    assert job.status is JobStatus.COMPLETED


def test_run_cycle_promotes_due_retries_before_claiming(
    dispatcher: JobDispatcher,
    job_queue: JobQueueService,
    job_repo: JobRepository,
    library_id: UUID,
    tmp_path: Path,
) -> None:
    job_id = job_queue.enqueue(
        JobType.SCAN_DIRECTORY,
        library_id,
        {"directory": str(tmp_path), "zone": "incoming"},
        now=_NOW,
    )
    job_repo.update_status(job_id, JobStatus.RETRY, scheduled_at=_NOW - timedelta(seconds=1))

    futures = dispatcher.run_cycle()

    assert len(futures) == 1
    futures[0].result(timeout=_POLL_TIMEOUT_SECONDS)
    assert job_repo.get(job_id).status is JobStatus.COMPLETED  # type: ignore[union-attr]


def test_start_and_stop_actually_process_a_job_end_to_end(
    dispatcher: JobDispatcher,
    job_queue: JobQueueService,
    job_repo: JobRepository,
    library_id: UUID,
    tmp_path: Path,
) -> None:
    audio_file = tmp_path / "track.flac"
    audio_file.write_bytes(b"content")
    job_id = job_queue.enqueue(
        JobType.SCAN_DIRECTORY,
        library_id,
        {"directory": str(tmp_path), "zone": "incoming"},
        now=_NOW,
    )

    dispatcher.start()
    try:
        assert _wait_until(lambda: job_repo.get(job_id).status is JobStatus.COMPLETED)  # type: ignore[union-attr]
    finally:
        dispatcher.stop()


def test_run_scan_marks_the_job_failed_if_the_scanner_worker_raises_unexpectedly(
    dispatcher: JobDispatcher,
    job_queue: JobQueueService,
    job_repo: JobRepository,
    library_id: UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job_id = job_queue.enqueue(
        JobType.SCAN_DIRECTORY, library_id, {"directory": "C:/x", "zone": "incoming"}, now=_NOW
    )
    job = job_repo.get(job_id)
    assert job is not None

    def _boom(_job: object) -> None:
        raise RuntimeError("scanner exploded")

    monkeypatch.setattr(dispatcher._scanner_worker, "execute", _boom)  # noqa: SLF001

    dispatcher._run_scan(job)  # noqa: SLF001

    updated = job_repo.get(job_id)
    assert updated is not None
    assert updated.status is JobStatus.RETRY
    assert updated.error_message == "scanner exploded"


def test_handle_cpu_result_marks_the_job_failed_if_handle_result_raises(
    dispatcher: JobDispatcher,
    job_queue: JobQueueService,
    job_repo: JobRepository,
    library_id: UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job_id = job_queue.enqueue(JobType.HASH_FILE, library_id, {}, now=_NOW)
    job = job_repo.get(job_id)
    assert job is not None

    def _boom(_job: object, _result: object) -> None:
        raise RuntimeError("handler exploded")

    monkeypatch.setattr(dispatcher._hash_worker, "handle_result", _boom)  # noqa: SLF001
    future: Future[dict[str, object]] = Future()
    future.set_result({"track_id": str(library_id)})

    dispatcher._handle_cpu_result(  # noqa: SLF001
        job,
        future,
        dispatcher._hash_worker.handle_result,
        "hash_file",  # noqa: SLF001
    )

    updated = job_repo.get(job_id)
    assert updated is not None
    assert updated.status is JobStatus.RETRY
    assert updated.error_message == "handler exploded"


def test_run_cycle_skips_process_pool_when_fingerprint_already_exists(
    dispatcher: JobDispatcher,
    job_queue: JobQueueService,
    job_repo: JobRepository,
    file_identity_repo: FileIdentityRepository,
    library_id: UUID,
    track_id: UUID,
) -> None:
    from musicvault.models.value_objects.file_identity import FileIdentity

    file_identity_repo.upsert(
        FileIdentity(
            track_id=track_id,
            content_hash_sha256="a" * 64,
            file_size=1,
            file_modified=_NOW,
            fingerprint_data=b"existing",
            fingerprint_hash="ff" * 32,
        )
    )
    job_id = job_queue.enqueue(
        JobType.FINGERPRINT_FILE,
        library_id,
        {"track_id": str(track_id), "file_path": "C:/x.flac"},
        now=_NOW,
    )

    futures = dispatcher.run_cycle()

    assert futures == []
    assert job_repo.get(job_id).status is JobStatus.COMPLETED  # type: ignore[union-attr]
    assert any(
        j.job_type is JobType.IDENTIFY_METADATA
        for j in job_repo.list_by_status(JobStatus.PENDING, library_id=library_id)
    )


def test_run_cycle_dispatches_a_fingerprint_file_job(
    dispatcher: JobDispatcher,
    job_queue: JobQueueService,
    job_repo: JobRepository,
    file_identity_repo: FileIdentityRepository,
    library_id: UUID,
    track_id: UUID,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from musicvault.models.interfaces.fingerprint import FingerprintResult
    from musicvault.models.value_objects.file_identity import FileIdentity

    audio = tmp_path / "track.flac"
    audio.write_bytes(b"audio")
    file_identity_repo.upsert(
        FileIdentity(
            track_id=track_id,
            content_hash_sha256="a" * 64,
            file_size=5,
            file_modified=_NOW,
        )
    )
    monkeypatch.setattr(
        "musicvault.workers.cpu.fingerprint_worker.generate_chromaprint",
        lambda _path: FingerprintResult(10.0, b"fp", "aa" * 32),
    )
    job_id = job_queue.enqueue(
        JobType.FINGERPRINT_FILE,
        library_id,
        {"track_id": str(track_id), "file_path": str(audio)},
        now=_NOW,
    )

    futures = dispatcher.run_cycle()
    assert len(futures) == 1
    futures[0].result(timeout=_POLL_TIMEOUT_SECONDS)

    assert job_repo.get(job_id).status is JobStatus.COMPLETED  # type: ignore[union-attr]


def test_poll_loop_survives_a_run_cycle_exception_and_keeps_polling(
    dispatcher: JobDispatcher,
    job_queue: JobQueueService,
    job_repo: JobRepository,
    library_id: UUID,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_run_cycle = dispatcher.run_cycle
    call_count = {"n": 0}

    def _flaky_run_cycle() -> list[object]:
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("transient poll failure")
        return real_run_cycle()  # type: ignore[return-value]

    monkeypatch.setattr(dispatcher, "run_cycle", _flaky_run_cycle)
    audio_file = tmp_path / "track.flac"
    audio_file.write_bytes(b"content")
    job_id = job_queue.enqueue(
        JobType.SCAN_DIRECTORY,
        library_id,
        {"directory": str(tmp_path), "zone": "incoming"},
        now=_NOW,
    )

    dispatcher.start()
    try:
        assert _wait_until(lambda: job_repo.get(job_id).status is JobStatus.COMPLETED)  # type: ignore[union-attr]
    finally:
        dispatcher.stop()
    assert call_count["n"] >= 2


def test_run_cycle_dispatches_an_identify_metadata_job(
    dispatcher: JobDispatcher,
    job_queue: JobQueueService,
    job_repo: JobRepository,
    track_repo: TrackRepository,
    library_id: UUID,
    track_id: UUID,
) -> None:
    from musicvault.models.entities.track import LibraryZone, Track

    track_repo.upsert(
        Track(
            id=track_id,
            library_id=library_id,
            zone=LibraryZone.INCOMING,
            file_path="C:/music/Artist - Album/01. Song Title.flac",
            file_name="01. Song Title.flac",
            file_size=1024,
            file_modified=_NOW,
            created_at=_NOW,
            updated_at=_NOW,
        )
    )
    job_id = job_queue.enqueue(
        JobType.IDENTIFY_METADATA,
        library_id,
        {"track_id": str(track_id)},
        now=_NOW,
    )

    futures = dispatcher.run_cycle()
    assert len(futures) == 1
    futures[0].result(timeout=_POLL_TIMEOUT_SECONDS)

    assert job_repo.get(job_id).status is JobStatus.COMPLETED  # type: ignore[union-attr]
    updated = track_repo.get_by_id(track_id)
    assert updated is not None
    assert updated.title == "Song Title"
    assert updated.needs_review is True
