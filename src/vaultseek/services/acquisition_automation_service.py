"""AcquisitionAutomationService — background auto-acquire + retries.

VaultSeek already has an acquisition UI page that can start work manually.
This service runs in the background to:

* auto-acquire jobs when their best score meets the configured threshold
* poll active downloads and chain verify → import
* schedule retries for failed acquisition jobs with exponential backoff
* re-score waiting jobs and periodically re-search ones without a download
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

from loguru import logger

from vaultseek.core.config import AcquisitionConfig, PipelineConfig
from vaultseek.core.event_bus import EventBus
from vaultseek.db.repositories.acquisition_job_repo import AcquisitionJobRepository
from vaultseek.db.repositories.library_repo import LibraryRepository
from vaultseek.models.entities.acquisition_job import AcquisitionJob, AcquisitionJobState
from vaultseek.services.acquisition_attention import park_if_attention_needed
from vaultseek.services.acquisition_bootstrap import connect_acquisition_providers
from vaultseek.services.acquisition_engine import AcquisitionEngine
from vaultseek.services.acquisition_labels import job_label
from vaultseek.services.acquisition_runner import AcquisitionRunner
from vaultseek.services.provider_manager import ProviderManager
from vaultseek.services.review_queue_service import ReviewQueueService
from vaultseek.services.wanted import is_parked

_FAILURE_STATES: tuple[AcquisitionJobState, ...] = (
    AcquisitionJobState.NO_RESULTS,
    AcquisitionJobState.DOWNLOAD_FAILED,
    AcquisitionJobState.VERIFICATION_FAILED,
    AcquisitionJobState.IMPORT_FAILED,
)

# Only terminal failures that may not have been parked at transition time.
# NO_RESULTS / WAITING_FOR_USER are parked once by AcquisitionRunner — re-parking
# hundreds of them every tick floods the event bus and freezes the UI.
_ATTENTION_STATES: tuple[AcquisitionJobState, ...] = (
    AcquisitionJobState.DOWNLOAD_FAILED,
    AcquisitionJobState.VERIFICATION_FAILED,
    AcquisitionJobState.IMPORT_FAILED,
)

_ATTENTION_PARK_BUDGET_PER_CYCLE = 10

_AUTO_ACQUIRE_STATES: tuple[AcquisitionJobState, ...] = (
    AcquisitionJobState.CREATED,
    AcquisitionJobState.QUEUED,
    AcquisitionJobState.SCORING,
)


@dataclass(frozen=True, slots=True)
class AcquisitionAutomationConfig:
    poll_interval_seconds: float = 5.0
    max_retries: int = 5
    # Keep this low — each CREATED/QUEUED job triggers a Soulseek search.
    # The Nicotine+ SearchRateGate also spaces searches; bursting many jobs
    # per tick still blocks the automation loop for a long time.
    max_jobs_per_library_per_cycle: int = 1
    max_scoring_jobs_per_library_per_cycle: int = 5
    # After this age, waiting jobs are re-queued for a fresh Soulseek search.
    # Survives app restart because it uses job.updated_at from the DB.
    recheck_cooldown_seconds: float = 20.0 * 60.0
    # Exhausted NO_RESULTS (max retries used) wait longer before another pass.
    exhausted_recheck_cooldown_seconds: float = 60.0 * 60.0
    max_rechecks_per_library_per_cycle: int = 1


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
        acquisition_config: AcquisitionConfig,
        provider_manager: ProviderManager,
        automation_config: AcquisitionAutomationConfig | None = None,
        review_queue: ReviewQueueService | None = None,
    ) -> None:
        self._libraries = library_repo
        self._jobs = acquisition_job_repo
        self._engine = acquisition_engine
        self._runner = acquisition_runner
        self._pipeline = pipeline_config
        self._event_bus = event_bus
        self._acquisition_config = acquisition_config
        self._providers = provider_manager
        self._cfg = automation_config or AcquisitionAutomationConfig()
        self._reviews = review_queue
        self._last_provider_warning_at: float = 0.0

        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_auto_acquire_pending: dict[UUID, int] = {}
        self._last_wishlist_search_at: dict[UUID, float] = {}

    def set_acquisition_config(self, config: AcquisitionConfig) -> None:
        """Hot-reload acquisition prefs after Settings save (no restart)."""
        self._acquisition_config = config

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
        # Reconnect only when offline — probing Nicotine+ every 5s adds latency
        # and can stall the automation thread (and UI event flood).
        if not self._providers.has_connected_search_providers():
            connect_acquisition_providers(self._acquisition_config, self._providers)
        if (
            self._acquisition_config.nicotine_plus.enabled
            and not self._providers.has_connected_search_providers()
        ):
            now = time.monotonic()
            if now - self._last_provider_warning_at > 60.0:
                self._last_provider_warning_at = now
                logger.warning(
                    "Nicotine+ is enabled but not connected — acquisition searches will not "
                    "run until Nicotine+ is online (Settings → Test connection, then save)."
                )

        # 1) Retry policy first — it may move jobs back to queued.
        self._schedule_retries(library_id)

        # 2) Recover downloads orphaned by an app restart (in-memory handles lost).
        self._recover_orphaned_downloads(library_id)

        # 3) Poll active downloads and chain verify → import.
        self._runner.poll_active_jobs(library_id)

        # 4) Re-score waiting jobs (may start downloads without a new search).
        self._rescore_waiting(library_id)

        # 5–6) Fresh wishlist searches (rate-limited by optional hours setting).
        if self._wishlist_search_allowed(library_id):
            self._recheck_stale_jobs(library_id)
            searched = self._auto_acquire(library_id)
            if searched:
                self._last_wishlist_search_at[library_id] = time.monotonic()

        # 7) Surface stuck failures under Attention needed.
        self._park_attention_for_failures(library_id)

    def _wishlist_search_allowed(self, library_id: UUID) -> bool:
        hours = float(self._acquisition_config.wishlist_search_interval_hours or 0.0)
        if hours <= 0:
            return True
        last = self._last_wishlist_search_at.get(library_id)
        if last is None:
            return True
        return (time.monotonic() - last) >= hours * 3600.0

    def _count_jobs(self, library_id: UUID, states: tuple[AcquisitionJobState, ...]) -> int:
        total = 0
        for state in states:
            for job in self._jobs.list_by_library(library_id=library_id, state=state):
                if is_parked(job):
                    continue
                total += 1
        return total

    def _auto_acquire(self, library_id: UUID) -> bool:
        # Bound searches tightly — Soulseek bans accounts that flood searches.
        search_processed = 0
        scoring_processed = 0
        pending = self._count_jobs(library_id, _AUTO_ACQUIRE_STATES)
        last_pending = self._last_auto_acquire_pending.get(library_id)
        if pending and pending != last_pending:
            logger.info("Auto-acquire: {} job(s) ready to search or download", pending)
            self._last_auto_acquire_pending[library_id] = pending
        elif not pending and last_pending:
            self._last_auto_acquire_pending.pop(library_id, None)

        search_budget = self._cfg.max_jobs_per_library_per_cycle
        scoring_budget = self._cfg.max_scoring_jobs_per_library_per_cycle
        started_search = False

        for state in _AUTO_ACQUIRE_STATES:
            is_search_state = state in (
                AcquisitionJobState.CREATED,
                AcquisitionJobState.QUEUED,
            )
            budget = search_budget if is_search_state else scoring_budget
            processed = search_processed if is_search_state else scoring_processed
            if processed >= budget:
                continue
            jobs = self._jobs.list_by_library(library_id=library_id, state=state)
            for job in jobs:
                if is_search_state and search_processed >= search_budget:
                    break
                if not is_search_state and scoring_processed >= scoring_budget:
                    break
                if is_parked(job):
                    continue
                if is_search_state:
                    search_processed += 1
                    started_search = True
                else:
                    scoring_processed += 1
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
        return started_search

    def _rescore_waiting(self, library_id: UUID) -> None:
        budget = self._cfg.max_scoring_jobs_per_library_per_cycle
        jobs = self._jobs.list_by_library(
            library_id=library_id, state=AcquisitionJobState.WAITING_FOR_USER
        )
        for job in jobs:
            if budget <= 0:
                return
            if not (job.extra.get("search_results") or []):
                continue
            # Already re-scored with the current path-aware engine — leave for
            # periodic re-search instead of burning the budget every tick.
            if int(job.extra.get("score_schema") or 0) >= 2:
                continue
            budget -= 1
            try:
                self._runner.try_auto_acquire_if_ready(job.id)
            except Exception:
                logger.exception("Rescore failed for acquisition job {}", job.id)

    def _recheck_stale_jobs(self, library_id: UUID) -> None:
        """Re-queue jobs that never got a download so they search again later.

        Runs across restarts: age is based on persisted ``updated_at``.
        """
        budget = self._cfg.max_rechecks_per_library_per_cycle
        if budget <= 0:
            return
        now = datetime.now(UTC)
        cooldown = timedelta(seconds=self._cfg.recheck_cooldown_seconds)
        exhausted_cooldown = timedelta(seconds=self._cfg.exhausted_recheck_cooldown_seconds)

        waiting = self._jobs.list_by_library(
            library_id=library_id, state=AcquisitionJobState.WAITING_FOR_USER
        )
        for job in waiting:
            if budget <= 0:
                return
            if now - _aware(job.updated_at) < cooldown:
                continue
            if self._requeue_for_research(job, note="periodic recheck (waiting)"):
                budget -= 1

        no_results = self._jobs.list_by_library(
            library_id=library_id, state=AcquisitionJobState.NO_RESULTS
        )
        for job in no_results:
            if budget <= 0:
                return
            # Active retry path handles jobs under max_retries.
            if job.retry_count < self._cfg.max_retries:
                continue
            if now - _aware(job.updated_at) < exhausted_cooldown:
                continue
            if self._requeue_for_research(job, note="periodic recheck (no results)"):
                budget -= 1

    def _requeue_for_research(self, job: AcquisitionJob, *, note: str) -> bool:
        try:
            self._engine.update_extra(
                job.id,
                {
                    "search_results": [],
                    "scored_results": [],
                    "score_schema": 0,
                    "last_recheck_at": datetime.now(UTC).isoformat(),
                    "recheck_note": note,
                },
            )
            if job.state is AcquisitionJobState.NO_RESULTS:
                # Reset retry budget so the normal retry → queue path can fire
                # repeatedly over days without being stuck forever.
                loaded = self._engine.get(job.id)
                if loaded is None:
                    return False
                reset = replace(loaded, retry_count=0)
                self._jobs.create(reset)
                self._engine.schedule_retry(job.id, note=note)
            else:
                self._engine.queue(job.id)
            logger.info("Recheck queued for {}: {}", job_label(job), note)
            return True
        except Exception:
            logger.exception("Failed to requeue acquisition job {} for recheck", job.id)
            return False

    def _recover_orphaned_downloads(self, library_id: UUID) -> None:
        downloading = self._jobs.list_by_library(
            library_id=library_id, state=AcquisitionJobState.DOWNLOADING
        )
        for job in downloading:
            status = self._runner._downloads.poll(job.id)  # noqa: SLF001
            if status is not None:
                continue
            # No in-memory handle (typical after restart) — fail and retry.
            try:
                self._engine.advance(
                    job.id,
                    AcquisitionJobState.DOWNLOAD_FAILED,
                    note="download handle lost (app restart) — will retry",
                )
                logger.info(
                    "Orphaned download recovered for {} — marked failed for retry",
                    job_label(job),
                )
            except Exception:
                logger.exception("Failed to recover orphaned download {}", job.id)

    def _park_attention_for_failures(self, library_id: UUID) -> None:
        budget = _ATTENTION_PARK_BUDGET_PER_CYCLE
        for state in _ATTENTION_STATES:
            if budget <= 0:
                return
            for job in self._jobs.list_by_library(library_id=library_id, state=state):
                if budget <= 0:
                    return
                park_if_attention_needed(
                    self._reviews,
                    job,
                    message=job.error_message or "",
                    provider_offline=bool(job.extra.get("provider_offline")),
                )
                budget -= 1

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
            due_at = _aware(job.updated_at) + timedelta(seconds=delay_seconds)
            if now >= due_at:
                self._engine.queue(job.id)

    def _delay_seconds(self, attempt: int) -> float:
        base = float(self._pipeline.retry_base_delay_seconds)
        capped = float(self._pipeline.retry_max_delay_seconds)
        return min(base * (2 ** (attempt - 1)), capped)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value
