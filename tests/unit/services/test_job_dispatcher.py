"""Unit tests for musicvault.services.job_dispatcher.JobDispatcher."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest

from musicvault.db.repositories.file_identity_repo import FileIdentityRepository
from musicvault.db.repositories.job_repo import JobRepository
from musicvault.db.repositories.track_repo import TrackRepository
from musicvault.db.writer import DatabaseWriter
from musicvault.models.entities.job import JobStatus, JobType
from musicvault.services.job_dispatcher import JobDispatcher
from musicvault.services.job_queue_service import JobQueueService
from musicvault.workers.cpu.hash_worker import HashWorker
from musicvault.workers.io.scanner_worker import ScannerWorker

_NOW = datetime(2026, 7, 15, tzinfo=UTC)


@pytest.fixture
def dispatcher(
    job_queue: JobQueueService,
    track_repo: TrackRepository,
    file_identity_repo: FileIdentityRepository,
    database_writer: DatabaseWriter,
) -> Iterator[JobDispatcher]:
    scanner = ScannerWorker(track_repo, file_identity_repo, database_writer, job_queue)
    hasher = HashWorker(file_identity_repo, database_writer, job_queue)
    disp = JobDispatcher(
        job_queue,
        scanner,
        hasher,
        scanner_threads=1,
        hash_processes=1,
        claim_batch_size=10,
        poll_interval_seconds=0.05,
    )
    yield disp
    disp.stop()


def _wait_until(predicate: Callable[[], bool], *, timeout: float = 20.0) -> bool:
    """20s (not a tighter, snappier value) because `ProcessPoolExecutor`
    spawn time on Windows CI runners is meaningfully slower and more
    variable than on a local dev machine — the worker process has to
    boot a fresh interpreter and re-import SQLAlchemy et al. before
    `compute_hash` can even run."""
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
    futures[0].result(timeout=20)  # ThreadPool path: no done-callback race

    job = job_repo.get(job_id)
    assert job is not None
    assert job.status is JobStatus.COMPLETED


def test_run_cycle_dispatches_a_hash_file_job_via_the_process_pool(
    dispatcher: JobDispatcher,
    job_queue: JobQueueService,
    job_repo: JobRepository,
    database_writer: DatabaseWriter,
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

    dispatcher.run_cycle()

    assert _wait_until(lambda: job_repo.get(job_id).status is JobStatus.COMPLETED)  # type: ignore[union-attr]


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
    futures[0].result(timeout=20)
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


def test_handle_hash_result_marks_the_job_failed_if_handle_result_raises(
    dispatcher: JobDispatcher,
    job_queue: JobQueueService,
    job_repo: JobRepository,
    library_id: UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from concurrent.futures import Future

    job_id = job_queue.enqueue(JobType.HASH_FILE, library_id, {}, now=_NOW)
    job = job_repo.get(job_id)
    assert job is not None

    def _boom(_job: object, _result: object) -> None:
        raise RuntimeError("handler exploded")

    monkeypatch.setattr(dispatcher._hash_worker, "handle_result", _boom)  # noqa: SLF001
    future: Future[dict[str, object]] = Future()
    future.set_result({"track_id": str(library_id)})

    dispatcher._handle_hash_result(job, future)  # noqa: SLF001

    updated = job_repo.get(job_id)
    assert updated is not None
    assert updated.status is JobStatus.RETRY
    assert updated.error_message == "handler exploded"


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
