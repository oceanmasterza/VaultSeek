"""JobDispatcher — polls the job queue and dispatches ready jobs to
worker pools.

Phase 4 wired `scan_directory` (I/O — `ThreadPoolExecutor`) and
`hash_file` (CPU — `ProcessPoolExecutor`). Phase 5 adds
`fingerprint_file` on the same CPU process pool. Phase 6 adds
`identify_metadata` on a dedicated I/O thread pool (HTTP + Mutagen —
docs/architecture/08-performance.md, "Three-Tier Worker Model").
Phase 8 adds `evaluate_rules`, Phase 9 `detect_duplicates`,
Phase 10 `organize_file`, Phase 11 `fetch_artwork`, Phase 13
`generate_report`, and Phase 15 `sync_media_server` on that same I/O
metadata pool. Later phases add one route per new worker as it's built
rather than pre-registering pools for workers that don't exist yet.
"""

from __future__ import annotations

import os
import threading
from concurrent.futures import Future, ProcessPoolExecutor, ThreadPoolExecutor
from typing import Any

from loguru import logger

from musicvault.models.entities.job import Job, JobType
from musicvault.services.job_queue_service import JobQueueService
from musicvault.workers.cpu.fingerprint_worker import FingerprintWorker, compute_fingerprint
from musicvault.workers.cpu.hash_worker import HashWorker, compute_hash
from musicvault.workers.io.artwork_worker import ArtworkWorker
from musicvault.workers.io.duplicate_worker import DuplicateWorker
from musicvault.workers.io.media_server_worker import MediaServerWorker
from musicvault.workers.io.metadata_worker import MetadataWorker
from musicvault.workers.io.organizer_worker import OrganizerWorker
from musicvault.workers.io.report_worker import ReportWorker
from musicvault.workers.io.rule_worker import RuleWorker
from musicvault.workers.io.scanner_worker import ScannerWorker

# I/O (metadata) pool job types — claimed under a shared backpressure budget.
_META_JOB_TYPES: tuple[JobType, ...] = (
    JobType.IDENTIFY_METADATA,
    JobType.EVALUATE_RULES,
    JobType.DETECT_DUPLICATES,
    JobType.ORGANIZE_FILE,
    JobType.FETCH_ARTWORK,
    JobType.GENERATE_REPORT,
    JobType.SYNC_MEDIA_SERVER,
)

_CPU_JOB_TYPES: tuple[JobType, ...] = (
    JobType.HASH_FILE,
    JobType.FINGERPRINT_FILE,
)


class JobDispatcher:
    def __init__(
        self,
        job_queue: JobQueueService,
        scanner_worker: ScannerWorker,
        hash_worker: HashWorker,
        fingerprint_worker: FingerprintWorker,
        metadata_worker: MetadataWorker,
        rule_worker: RuleWorker,
        duplicate_worker: DuplicateWorker,
        organizer_worker: OrganizerWorker,
        artwork_worker: ArtworkWorker,
        report_worker: ReportWorker,
        media_server_worker: MediaServerWorker,
        *,
        scanner_threads: int = 1,
        hash_processes: int | None = None,
        metadata_threads: int = 1,
        claim_batch_size: int = 10,
        poll_interval_seconds: float = 1.0,
    ) -> None:
        self._job_queue = job_queue
        self._scanner_worker = scanner_worker
        self._hash_worker = hash_worker
        self._fingerprint_worker = fingerprint_worker
        self._metadata_worker = metadata_worker
        self._rule_worker = rule_worker
        self._duplicate_worker = duplicate_worker
        self._organizer_worker = organizer_worker
        self._artwork_worker = artwork_worker
        self._report_worker = report_worker
        self._media_server_worker = media_server_worker
        self._claim_batch_size = claim_batch_size
        self._poll_interval_seconds = poll_interval_seconds
        self._scan_max = max(1, scanner_threads)
        self._meta_max = max(1, metadata_threads)
        # ProcessPoolExecutor(None) uses min(32, cpu_count+4); mirror that for budgeting.
        self._cpu_max = (
            hash_processes if hash_processes is not None else min(32, (os.cpu_count() or 1) + 4)
        )
        self._scan_pool = ThreadPoolExecutor(
            max_workers=self._scan_max, thread_name_prefix="musicvault-scan"
        )
        # Shared CPU ProcessPool for hash_file and fingerprint_file —
        # both are Tier 1 CPU-bound work (08-performance.md).
        self._cpu_pool = ProcessPoolExecutor(max_workers=hash_processes)
        # Dedicated I/O ThreadPool for identify_metadata + evaluate_rules
        # (Tier 2). Kept separate from scan so slow HTTP cannot starve
        # directory walks.
        self._metadata_pool = ThreadPoolExecutor(
            max_workers=self._meta_max, thread_name_prefix="musicvault-meta"
        )
        self._shutdown = threading.Event()
        self._thread: threading.Thread | None = None
        self._inflight_lock = threading.Lock()
        self._scan_inflight = 0
        self._cpu_inflight = 0
        self._meta_inflight = 0

    def recover(self) -> int:
        """Reset any jobs left `running` by a previous crash. Call once,
        before :meth:`start`."""
        return self._job_queue.recover_orphaned()

    def run_cycle(self) -> list[Future[Any]]:
        """Claim and dispatch one round of ready work.

        Claims are limited by free pool slots so jobs are not marked
        ``running`` faster than workers can execute them.

        Returns the futures submitted this cycle — mainly so tests can
        wait on them deterministically instead of polling on a timer.
        Note that for CPU-pool futures, `.result()` completing does
        not guarantee the corresponding ``handle_result`` has *also*
        finished running — see the done-callback caveat on
        :meth:`_handle_cpu_result`.
        """
        self._job_queue.promote_due_retries()

        scan_jobs = self._claim_up_to("scan", JobType.SCAN_DIRECTORY)
        cpu_jobs = self._claim_shared("cpu", _CPU_JOB_TYPES)
        hash_jobs = cpu_jobs[JobType.HASH_FILE]
        fingerprint_jobs = cpu_jobs[JobType.FINGERPRINT_FILE]
        meta_jobs = self._claim_shared("meta", _META_JOB_TYPES)

        futures: list[Future[Any]] = []
        for job in scan_jobs:
            futures.append(self._submit_scan(job))
        for job in hash_jobs:
            futures.append(self._submit_cpu(job, compute_hash, self._make_hash_callback(job)))
        for job in fingerprint_jobs:
            if self._fingerprint_worker.already_fingerprinted(job):
                self._fingerprint_worker.complete_without_recompute(job)
                continue
            futures.append(
                self._submit_cpu(job, compute_fingerprint, self._make_fingerprint_callback(job))
            )

        runners = {
            JobType.IDENTIFY_METADATA: self._run_metadata,
            JobType.EVALUATE_RULES: self._run_rules,
            JobType.DETECT_DUPLICATES: self._run_duplicates,
            JobType.ORGANIZE_FILE: self._run_organize,
            JobType.FETCH_ARTWORK: self._run_artwork,
            JobType.GENERATE_REPORT: self._run_report,
            JobType.SYNC_MEDIA_SERVER: self._run_media_server,
        }
        for job_type, jobs in meta_jobs.items():
            runner = runners[job_type]
            for job in jobs:
                futures.append(self._submit_meta(runner, job))
        return futures

    def _free_slots(self, pool: str) -> int:
        with self._inflight_lock:
            if pool == "scan":
                return max(0, self._scan_max - self._scan_inflight)
            if pool == "cpu":
                return max(0, self._cpu_max - self._cpu_inflight)
            return max(0, self._meta_max - self._meta_inflight)

    def _claim_up_to(self, pool: str, job_type: JobType) -> list[Job]:
        free = self._free_slots(pool)
        if free <= 0:
            return []
        return list(self._job_queue.claim_pending(job_type, min(self._claim_batch_size, free)))

    def _claim_shared(self, pool: str, job_types: tuple[JobType, ...]) -> dict[JobType, list[Job]]:
        """Claim across multiple job types under one pool capacity budget."""
        free = self._free_slots(pool)
        claimed: dict[JobType, list[Job]] = {}
        for job_type in job_types:
            if free <= 0:
                claimed[job_type] = []
                continue
            jobs = list(self._job_queue.claim_pending(job_type, min(self._claim_batch_size, free)))
            free -= len(jobs)
            claimed[job_type] = jobs
        return claimed

    def _bump_inflight(self, pool: str, delta: int) -> None:
        with self._inflight_lock:
            if pool == "scan":
                self._scan_inflight += delta
            elif pool == "cpu":
                self._cpu_inflight += delta
            else:
                self._meta_inflight += delta

    def _submit_scan(self, job: Job) -> Future[Any]:
        self._bump_inflight("scan", 1)

        def _run() -> None:
            try:
                self._run_scan(job)
            finally:
                self._bump_inflight("scan", -1)

        return self._scan_pool.submit(_run)

    def _submit_meta(self, runner: Any, job: Job) -> Future[Any]:
        self._bump_inflight("meta", 1)

        def _run() -> None:
            try:
                runner(job)
            finally:
                self._bump_inflight("meta", -1)

        return self._metadata_pool.submit(_run)

    def _submit_cpu(
        self,
        job: Job,
        compute: Any,
        callback: Any,
    ) -> Future[Any]:
        self._bump_inflight("cpu", 1)
        future = self._cpu_pool.submit(compute, job.payload)

        def _on_done(done: Future[dict[str, Any]]) -> None:
            try:
                callback(done)
            finally:
                self._bump_inflight("cpu", -1)

        future.add_done_callback(_on_done)
        return future

    def start(self) -> None:
        """Start polling in a background thread. Safe to call once per instance."""
        self._thread = threading.Thread(
            target=self._poll_loop, name="musicvault-dispatcher", daemon=True
        )
        self._thread.start()

    def stop(self, *, timeout: float | None = 10.0) -> None:
        """Stop polling and shut down all worker pools, waiting for any
        in-flight work to finish."""
        self._shutdown.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
        self._scan_pool.shutdown(wait=True)
        self._cpu_pool.shutdown(wait=True)
        self._metadata_pool.shutdown(wait=True)

    def _poll_loop(self) -> None:
        while not self._shutdown.is_set():
            try:
                self.run_cycle()
            except Exception:
                logger.exception("JobDispatcher poll cycle failed")
            self._shutdown.wait(timeout=self._poll_interval_seconds)

    def _run_scan(self, job: Job) -> None:
        """Runs on a `_scan_pool` thread. Unlike the hash/fingerprint
        pipeline, this can call `JobQueueService` directly on failure —
        no process boundary, no done-callback race."""
        try:
            self._scanner_worker.execute(job)
        except Exception as exc:
            logger.exception("ScannerWorker crashed on job {}", job.id)
            self._job_queue.mark_failed(job.id, str(exc))

    def _run_metadata(self, job: Job) -> None:
        """Runs on a `_metadata_pool` thread (I/O — HTTP + Mutagen)."""
        try:
            self._metadata_worker.execute(job)
        except Exception as exc:
            logger.exception("MetadataWorker crashed on job {}", job.id)
            self._job_queue.mark_failed(job.id, str(exc))

    def _run_rules(self, job: Job) -> None:
        """Runs on a `_metadata_pool` thread (DB + rule AST evaluation)."""
        try:
            self._rule_worker.execute(job)
        except Exception as exc:
            logger.exception("RuleWorker crashed on job {}", job.id)
            self._job_queue.mark_failed(job.id, str(exc))

    def _run_duplicates(self, job: Job) -> None:
        """Runs on a `_metadata_pool` thread (DB reads + in-memory grouping)."""
        try:
            self._duplicate_worker.execute(job)
        except Exception as exc:
            logger.exception("DuplicateWorker crashed on job {}", job.id)
            self._job_queue.mark_failed(job.id, str(exc))

    def _run_organize(self, job: Job) -> None:
        """Runs on a `_metadata_pool` thread (filesystem move + DB writes)."""
        try:
            self._organizer_worker.execute(job)
        except Exception as exc:
            logger.exception("OrganizerWorker crashed on job {}", job.id)
            self._job_queue.mark_failed(job.id, str(exc))

    def _run_artwork(self, job: Job) -> None:
        """Runs on a `_metadata_pool` thread (HTTP + Mutagen + cache writes)."""
        try:
            self._artwork_worker.execute(job)
        except Exception as exc:
            logger.exception("ArtworkWorker crashed on job {}", job.id)
            self._job_queue.mark_failed(job.id, str(exc))

    def _run_report(self, job: Job) -> None:
        """Runs on a `_metadata_pool` thread (DB aggregates + report write)."""
        try:
            self._report_worker.execute(job)
        except Exception as exc:
            logger.exception("ReportWorker crashed on job {}", job.id)
            self._job_queue.mark_failed(job.id, str(exc))

    def _run_media_server(self, job: Job) -> None:
        """Runs on a `_metadata_pool` thread (HTTP to media servers)."""
        try:
            self._media_server_worker.execute(job)
        except Exception as exc:
            logger.exception("MediaServerWorker crashed on job {}", job.id)
            self._job_queue.mark_failed(job.id, str(exc))

    def _make_hash_callback(self, job: Job) -> Any:
        def _on_done(future: Future[dict[str, Any]]) -> None:
            self._handle_cpu_result(job, future, self._hash_worker.handle_result, "hash_file")

        return _on_done

    def _make_fingerprint_callback(self, job: Job) -> Any:
        def _on_done(future: Future[dict[str, Any]]) -> None:
            self._handle_cpu_result(
                job, future, self._fingerprint_worker.handle_result, "fingerprint_file"
            )

        return _on_done

    def _handle_cpu_result(
        self,
        job: Job,
        future: Future[dict[str, Any]],
        handler: Any,
        job_label: str,
    ) -> None:
        """Runs on the `ProcessPoolExecutor`'s internal callback thread,
        once the CPU worker returns — not on `_cpu_pool`'s worker
        process itself, and not synchronously with whatever called
        `future.result()` elsewhere (`Future.set_result` notifies
        waiters *before* invoking done-callbacks, so `.result()`
        returning is not proof this method has run — see the CPython
        `concurrent.futures._base.Future.set_result` source)."""
        try:
            result = future.result()
            handler(job, result)
        except Exception as exc:
            logger.exception("Failed to handle {} result for job {}", job_label, job.id)
            self._job_queue.mark_failed(job.id, str(exc))
