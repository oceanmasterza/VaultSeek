"""AcquisitionAutomationService — background auto-acquire + retries.

VaultSeek already has an acquisition UI page that can start work manually.
This service runs in the background to:

* auto-acquire jobs when their best score meets the configured threshold
* poll active downloads and chain verify → import
* schedule retries for failed acquisition jobs with exponential backoff

It is intentionally conservative: it never attempts to auto-acquire jobs in
`waiting_for_user` because those require user confirmation.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from loguru import logger

from vaultseek.core.config import PipelineConfig
from vaultseek.core.event_bus import EventBus
from vaultseek.db.repositories.acquisition_job_repo import AcquisitionJobRepository
from vaultseek.db.repositories.library_repo import LibraryRepository
from vaultseek.models.entities.acquisition_job import AcquisitionJobState
from vaultseek.services.acquisition_attention import park_if_attention_needed
from vaultseek.services.acquisition_engine import AcquisitionEngine
from vaultseek.services.acquisition_runner import AcquisitionRunner
from vaultseek.services.review_queue_service import ReviewQueueService

_FAILURE_STATES: tuple[AcquisitionJobState, ...] = (
    AcquisitionJobState.DOWNLOAD_FAILED,
    AcquisitionJobState.VERIFICATION_FAILED,
    AcquisitionJobState.IMPORT_FAILED,
)

_ATTENTION_STATES: tuple[AcquisitionJobState, ...] = (
    AcquisitionJobState.NO_RESULTS,
    AcquisitionJobState.DOWNLOAD_FAILED,
    AcquisitionJobState.VERIFICATION_FAILED,
    AcquisitionJobState.IMPORT_FAILED,
)

_AUTO_ACQUIRE_STATES: tuple[AcquisitionJobState, ...] = (
    AcquisitionJobState.CREATED,
    AcquisitionJobState.QUEUED,
    AcquisitionJobState.SCORING,
)


@dataclass(frozen=True, slots=True)
class AcquisitionAutomationConfig:
    poll_interval_seconds: float = 5.0
    max_retries: int = 5
    max_jobs_per_library_per_cycle: int = 10


class AcquisitionAutomationService:
    """Background loop for acquisition job automation."""

    def __init__(
        self,
        *,
        library_repo: LibraryRepository,
        acquisition_job_repo: AcquisitionJobRepository,
        acquisition_engine: AcquisitionEngine,
        acquisition_runner: AcquisitionRunner,
        pipeline_config: PipelineConfig,
        event_bus: EventBus,
        automation_config: AcquisitionAutomationConfig | None = None,
        review_queue: ReviewQueueService | None = None,
    ) -> None:
        self._libraries = library_repo
        self._jobs = acquisition_job_repo
        self._engine = acquisition_engine
        self._runner = acquisition_runner
        self._pipeline = pipeline_config
        self._event_bus = event_bus
        self._cfg = automation_config or AcquisitionAutomationConfig()
        self._reviews = review_queue

        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def _run_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._tick_all_libraries()
            except Exception:
                logger.exception("Acquisition automation loop tick failed")
            self._stop.wait(self._cfg.poll_interval_seconds)

    def _tick_all_libraries(self) -> None:
        libraries = self._libraries.list_all()
        for library in libraries:
            if self._stop.is_set():
                return
            try:
                self._tick_library(library.id)
            except Exception:
                logger.exception(
                    "Acquisition automation tick failed for library {}",
                    library.id,
                )

    def _tick_library(self, library_id: UUID) -> None:
        # 1) Retry policy first — it may move jobs back to queued.
        self._schedule_retries(library_id)

        # 2) Poll active downloads and chain verify → import.
        self._runner.poll_active_jobs(library_id)

        # 3) Auto-acquire for jobs that are eligible and unsupervised.
        self._auto_acquire(library_id)

        # 4) Surface stuck failures under Attention needed.
        self._park_attention_for_failures(library_id)

    def _auto_acquire(self, library_id: UUID) -> None:
        # Keep it bounded to avoid long loops if many jobs exist.
        processed = 0
        for state in _AUTO_ACQUIRE_STATES:
            if processed >= self._cfg.max_jobs_per_library_per_cycle:
                return
            jobs = self._jobs.list_by_library(library_id=library_id, state=state)
            for job in jobs:
                if processed >= self._cfg.max_jobs_per_library_per_cycle:
                    return
                processed += 1
                try:
                    self._runner.try_auto_acquire_if_ready(job.id)
                except Exception:
                    logger.exception(
                        "Auto-acquire failed for acquisition job {}",
                        job.id,
                    )
                    loaded = self._engine.get(job.id)
                    park_if_attention_needed(
                        self._reviews,
                        loaded,
                        message="auto-acquire raised an unexpected error",
                    )

    def _park_attention_for_failures(self, library_id: UUID) -> None:
        for state in _ATTENTION_STATES:
            for job in self._jobs.list_by_library(library_id=library_id, state=state):
                park_if_attention_needed(
                    self._reviews,
                    job,
                    message=job.error_message or "",
                    provider_offline=bool(job.extra.get("provider_offline")),
                )

    def _schedule_retries(self, library_id: UUID) -> None:
        # Failures → retry scheduled (increment retry_count once, atomically).
        for state in _FAILURE_STATES:
            jobs = self._jobs.list_by_library(library_id=library_id, state=state)
            for job in jobs:
                if job.retry_count >= self._cfg.max_retries:
                    continue
                self._engine.schedule_retry(job.id, note=f"auto retry from {state.value}")

        # RETRY_SCHEDULED → QUEUED when enough delay elapsed.
        scheduled = self._jobs.list_by_library(
            library_id=library_id, state=AcquisitionJobState.RETRY_SCHEDULED
        )
        now = datetime.now(UTC)
        for job in scheduled:
            # retry_count==1 means "first retry" with base delay.
            attempt = max(job.retry_count, 1)
            delay_seconds = self._delay_seconds(attempt)
            due_at = job.updated_at + timedelta(seconds=delay_seconds)
            if now >= due_at:
                self._engine.queue(job.id)

    def _delay_seconds(self, attempt: int) -> float:
        base = float(self._pipeline.retry_base_delay_seconds)
        capped = float(self._pipeline.retry_max_delay_seconds)
        return min(base * (2 ** (attempt - 1)), capped)
