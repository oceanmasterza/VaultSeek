"""JobDispatcher — polls the job queue and dispatches ready jobs to
worker pools.

Phase 4 wired `scan_directory` (I/O — `ThreadPoolExecutor`) and
`hash_file` (CPU — `ProcessPoolExecutor`). Phase 5 adds
`fingerprint_file` on the same CPU process pool. Phase 6 adds
`identify_metadata` on a dedicated I/O thread pool (HTTP + Mutagen —
docs/architecture/08-performance.md, "Three-Tier Worker Model").
Phase 8 adds `evaluate_rules`, Phase 9 `detect_duplicates`,
Phase 10 `organize_file`, and Phase 11 `fetch_artwork` on that same
I/O metadata pool (DB reads, light in-memory work, HTTP, file moves).
Later phases add one route per new worker as it's built rather than
pre-registering pools for workers that don't exist yet.
"""

from __future__ import annotations

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
from musicvault.workers.io.metadata_worker import MetadataWorker
from musicvault.workers.io.organizer_worker import OrganizerWorker
from musicvault.workers.io.rule_worker import RuleWorker
from musicvault.workers.io.scanner_worker import ScannerWorker


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
        self._claim_batch_size = claim_batch_size
        self._poll_interval_seconds = poll_interval_seconds
        self._scan_pool = ThreadPoolExecutor(
            max_workers=scanner_threads, thread_name_prefix="musicvault-scan"
        )
        # Shared CPU ProcessPool for hash_file and fingerprint_file —
        # both are Tier 1 CPU-bound work (08-performance.md).
        self._cpu_pool = ProcessPoolExecutor(max_workers=hash_processes)
        # Dedicated I/O ThreadPool for identify_metadata + evaluate_rules
        # (Tier 2). Kept separate from scan so slow HTTP cannot starve
        # directory walks.
        self._metadata_pool = ThreadPoolExecutor(
            max_workers=metadata_threads, thread_name_prefix="musicvault-meta"
        )
        self._shutdown = threading.Event()
        self._thread: threading.Thread | None = None

    def recover(self) -> int:
        """Reset any jobs left `running` by a previous crash. Call once,
        before :meth:`start`."""
        return self._job_queue.recover_orphaned()

    def run_cycle(self) -> list[Future[Any]]:
        """Claim and dispatch one round of ready work.

        Returns the futures submitted this cycle — mainly so tests can
        wait on them deterministically instead of polling on a timer.
        Note that for CPU-pool futures, `.result()` completing does
        not guarantee the corresponding ``handle_result`` has *also*
        finished running — see the done-callback caveat on
        :meth:`_handle_cpu_result`.
        """
        self._job_queue.promote_due_retries()

        # Claim every route first, then dispatch. Workers that complete
        # synchronously (or via done-callbacks) may enqueue the next
        # pipeline stage; claiming up front keeps those new jobs for the
        # following cycle instead of nesting work inside this one.
        scan_jobs = list(
            self._job_queue.claim_pending(JobType.SCAN_DIRECTORY, self._claim_batch_size)
        )
        hash_jobs = list(self._job_queue.claim_pending(JobType.HASH_FILE, self._claim_batch_size))
        fingerprint_jobs = list(
            self._job_queue.claim_pending(JobType.FINGERPRINT_FILE, self._claim_batch_size)
        )
        metadata_jobs = list(
            self._job_queue.claim_pending(JobType.IDENTIFY_METADATA, self._claim_batch_size)
        )
        rule_jobs = list(
            self._job_queue.claim_pending(JobType.EVALUATE_RULES, self._claim_batch_size)
        )
        duplicate_jobs = list(
            self._job_queue.claim_pending(JobType.DETECT_DUPLICATES, self._claim_batch_size)
        )
        organize_jobs = list(
            self._job_queue.claim_pending(JobType.ORGANIZE_FILE, self._claim_batch_size)
        )
        artwork_jobs = list(
            self._job_queue.claim_pending(JobType.FETCH_ARTWORK, self._claim_batch_size)
        )

        futures: list[Future[Any]] = []
        for job in scan_jobs:
            futures.append(self._scan_pool.submit(self._run_scan, job))
        for job in hash_jobs:
            future = self._cpu_pool.submit(compute_hash, job.payload)
            future.add_done_callback(self._make_hash_callback(job))
            futures.append(future)
        for job in fingerprint_jobs:
            if self._fingerprint_worker.already_fingerprinted(job):
                self._fingerprint_worker.complete_without_recompute(job)
                continue
            future = self._cpu_pool.submit(compute_fingerprint, job.payload)
            future.add_done_callback(self._make_fingerprint_callback(job))
            futures.append(future)
        for job in metadata_jobs:
            futures.append(self._metadata_pool.submit(self._run_metadata, job))
        for job in rule_jobs:
            futures.append(self._metadata_pool.submit(self._run_rules, job))
        for job in duplicate_jobs:
            futures.append(self._metadata_pool.submit(self._run_duplicates, job))
        for job in organize_jobs:
            futures.append(self._metadata_pool.submit(self._run_organize, job))
        for job in artwork_jobs:
            futures.append(self._metadata_pool.submit(self._run_artwork, job))
        return futures

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
