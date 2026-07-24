"""AcquisitionRunner — search, score, auto-acquire, and poll active downloads."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from loguru import logger

from vaultseek.core.config import AcquisitionConfig
from vaultseek.db.repositories.library_repo import LibraryRepository
from vaultseek.models.entities.acquisition_job import (
    AcquisitionJob,
    AcquisitionJobState,
    AcquisitionJobType,
)
from vaultseek.models.interfaces.acquisition import SearchResult
from vaultseek.services.acquisition_attention import park_if_attention_needed
from vaultseek.services.acquisition_engine import AcquisitionEngine
from vaultseek.services.acquisition_labels import job_label
from vaultseek.services.acquisition_outcomes import (
    AcquisitionOutcomeCode,
    classify_download_message,
    classify_verification_failures,
    outcome_extra,
)
from vaultseek.services.acquisition_workflow import AcquisitionWorkflow
from vaultseek.services.download_manager import DownloadManager
from vaultseek.services.review_queue_service import ReviewQueueService
from vaultseek.services.scoring_engine import ScoringEngine
from vaultseek.services.search_dispatcher import SearchDispatcher
from vaultseek.services.wanted import is_parked


@dataclass(frozen=True, slots=True)
class RunnerOutcome:
    """Result of one acquisition runner step."""

    job_id: UUID
    state: AcquisitionJobState
    message: str = ""
    best_score: float | None = None
    scored_count: int = 0


class AcquisitionRunner:
    """Orchestrates search → score → download → verify → import."""

    def __init__(
        self,
        acquisition_engine: AcquisitionEngine,
        search_dispatcher: SearchDispatcher,
        scoring_engine: ScoringEngine,
        download_manager: DownloadManager,
        acquisition_workflow: AcquisitionWorkflow,
        *,
        auto_acquire_threshold: float = 0.90,
        review_queue: ReviewQueueService | None = None,
        library_repo: LibraryRepository | None = None,
        acquisition_config: AcquisitionConfig | None = None,
    ) -> None:
        self._engine = acquisition_engine
        self._search = search_dispatcher
        self._scoring = scoring_engine
        self._downloads = download_manager
        self._workflow = acquisition_workflow
        self._threshold = auto_acquire_threshold
        self._reviews = review_queue
        self._libraries = library_repo
        self._acquisition_config = acquisition_config or AcquisitionConfig()
        self._download_progress_logged: dict[UUID, int] = {}
        self._last_active_download_count: int | None = None

    @property
    def auto_acquire_threshold(self) -> float:
        return self._threshold

    def set_auto_acquire_threshold(self, threshold: float) -> None:
        self._threshold = threshold

    def search_and_score(self, job_id: UUID) -> RunnerOutcome:
        job = self._engine.get(job_id)
        if job is None:
            raise KeyError(f"AcquisitionJob {job_id} not found")

        if job.state is AcquisitionJobState.CREATED:
            self._engine.queue(job_id)

        results = self._search.dispatch(job_id)
        job = self._engine.get(job_id)
        assert job is not None

        if job.state is AcquisitionJobState.QUEUED and job.extra.get("search_deferred"):
            retry_after = float(job.extra.get("search_retry_after_seconds") or 0.0)
            message = f"deferred — Soulseek search rate limit ({retry_after:.0f}s)"
            logger.info("Search for {}: {}", job_label(job), message)
            return RunnerOutcome(job_id, AcquisitionJobState.QUEUED, message)

        if job.state is AcquisitionJobState.QUEUED and job.extra.get("search_deferred"):
            retry_after = float(job.extra.get("search_retry_after_seconds") or 0.0)
            message = f"deferred — Soulseek search rate limit ({retry_after:.0f}s)"
            logger.info("Search for {}: {}", job_label(job), message)
            return RunnerOutcome(job_id, AcquisitionJobState.QUEUED, message)

        if job.state is AcquisitionJobState.NO_RESULTS or not results:
            provider_offline = bool(job.extra.get("provider_offline"))
            exhausted = bool(job.extra.get("search_exhausted"))
            message = (
                job.error_message
                or (
                    "no acquisition providers connected"
                    if provider_offline
                    else "no Soulseek hits"
                )
            )
            if exhausted:
                logger.warning("Search for {}: exhausted — {}", job_label(job), message)
                self._park_attention(job, message=message, provider_offline=False)
            else:
                logger.info(
                    "Search for {}: {} — will retry (not parked in Review)",
                    job_label(job),
                    message,
                )
            return RunnerOutcome(job_id, AcquisitionJobState.NO_RESULTS, message)

        self._engine.advance(job_id, AcquisitionJobState.SCORING, note=f"{len(results)} hit(s)")
        job = self._engine.get(job_id)
        assert job is not None

        scored = self._scoring.score_results(job, results)
        self._engine.update_extra(
            job_id,
            {
                "search_results": [_result_to_dict(item) for item, _ in scored],
                "scored_results": [
                    {"result_id": item.result_id, "provider_id": item.provider_id, "score": score}
                    for item, score in scored
                ],
            },
        )
        best_score = scored[0][1] if scored else None
        if scored:
            logger.info(
                "Scored {} hit(s) for {} (best {:.0%})",
                len(scored),
                job_label(job),
                best_score or 0.0,
            )
        return RunnerOutcome(
            job_id,
            AcquisitionJobState.SCORING,
            f"scored {len(scored)} result(s)",
            best_score=best_score,
            scored_count=len(scored),
        )

    def try_auto_acquire(self, job_id: UUID, *, auto_import: bool = True) -> RunnerOutcome:
        job = self._engine.get(job_id)
        if job is None:
            raise KeyError(f"AcquisitionJob {job_id} not found")
        if is_parked(job):
            return RunnerOutcome(
                job_id,
                job.state,
                "parked on Wanted shelf — use Start download to search",
            )

        outcome = self.search_and_score(job_id)
        job = self._engine.get(job_id)
        if job is None:
            raise KeyError(f"AcquisitionJob {job_id} not found")

        if job.state is AcquisitionJobState.NO_RESULTS:
            return outcome
        if job.state is AcquisitionJobState.QUEUED:
            return outcome

        return self._auto_acquire_from_scored(job_id, auto_import=auto_import, prior=outcome)

    def try_auto_acquire_if_ready(
        self,
        job_id: UUID,
        *,
        auto_import: bool = True,
    ) -> RunnerOutcome | None:
        """Background-safe auto-acquire: search only when the job still needs it."""
        job = self._engine.get(job_id)
        if job is None:
            raise KeyError(f"AcquisitionJob {job_id} not found")
        if is_parked(job):
            return None

        if job.state in (AcquisitionJobState.CREATED, AcquisitionJobState.QUEUED):
            return self.try_auto_acquire(job_id, auto_import=auto_import)

        if job.state is AcquisitionJobState.SCORING:
            return self._auto_acquire_from_scored(job_id, auto_import=auto_import)

        if job.state is AcquisitionJobState.WAITING_FOR_USER:
            return self._rescore_waiting_and_acquire(job_id, auto_import=auto_import)

        return None

    def _rescore_waiting_and_acquire(
        self,
        job_id: UUID,
        *,
        auto_import: bool = True,
    ) -> RunnerOutcome:
        """Re-score stored Nicotine hits (no new Soulseek search) and download if OK."""
        job = self._engine.get(job_id)
        if job is None:
            raise KeyError(f"AcquisitionJob {job_id} not found")
        results = [
            _result_from_dict(item)
            for item in job.extra.get("search_results") or []
            if isinstance(item, dict) and item.get("result_id")
        ]
        if not results:
            return RunnerOutcome(
                job_id,
                AcquisitionJobState.WAITING_FOR_USER,
                "no stored results to rescore",
            )

        scored = self._scoring.score_results(job, results)
        self._engine.update_extra(
            job_id,
            {
                "search_results": [_result_to_dict(item) for item, _ in scored],
                "scored_results": [
                    {
                        "result_id": item.result_id,
                        "provider_id": item.provider_id,
                        "score": score,
                    }
                    for item, score in scored
                ],
                "rescored_at": datetime.now(UTC).isoformat(),
                "score_schema": 2,
            },
        )
        best_score = scored[0][1] if scored else 0.0
        if best_score < self._threshold:
            logger.debug(
                "{}: rescored best {:.0%} still below threshold {:.0%}",
                job_label(job),
                best_score,
                self._threshold,
            )
            return RunnerOutcome(
                job_id,
                AcquisitionJobState.WAITING_FOR_USER,
                "still below auto-acquire threshold",
                best_score=best_score,
                scored_count=len(scored),
            )

        logger.info(
            "{}: rescored best {:.0%} meets threshold {:.0%} — starting download",
            job_label(job),
            best_score,
            self._threshold,
        )
        return self.start_download(
            job_id, scored[0][0], auto_import=auto_import, score=best_score
        )

    def _auto_acquire_from_scored(
        self,
        job_id: UUID,
        *,
        auto_import: bool = True,
        prior: RunnerOutcome | None = None,
    ) -> RunnerOutcome:
        job = self._engine.get(job_id)
        if job is None:
            raise KeyError(f"AcquisitionJob {job_id} not found")

        # Always re-score from stored hits so scoring improvements apply without
        # another Soulseek search.
        results = [
            _result_from_dict(item)
            for item in job.extra.get("search_results") or []
            if isinstance(item, dict) and item.get("result_id")
        ]
        if results:
            scored = self._scoring.score_results(job, results)
            self._engine.update_extra(
                job_id,
                {
                    "scored_results": [
                        {
                            "result_id": item.result_id,
                            "provider_id": item.provider_id,
                            "score": score,
                        }
                        for item, score in scored
                    ],
                    "score_schema": 2,
                },
            )
        else:
            scored = _load_scored(job)
        if not scored:
            self._engine.advance(job_id, AcquisitionJobState.NO_RESULTS, note="nothing to score")
            self._engine.update_extra(
                job_id,
                outcome_extra(
                    AcquisitionOutcomeCode.SEARCH_EMPTY,
                    detail="hits filtered to zero by scoring",
                    search_exhausted=False,
                ),
            )
            job = self._engine.get(job_id)
            assert job is not None
            logger.info("{}: no scored audio results — will retry", job_label(job))
            return RunnerOutcome(job_id, AcquisitionJobState.NO_RESULTS, "no scored results")

        best_result, best_score = scored[0]
        below_attempts = int(job.extra.get("below_threshold_attempts") or 0)
        # After several below-threshold passes, accept a weaker but still
        # plausible hit so automation is not stuck forever on quality.
        effective_threshold = self._threshold
        if below_attempts >= 3:
            effective_threshold = min(self._threshold, 0.28)

        if best_score < effective_threshold:
            self._engine.advance(
                job_id,
                AcquisitionJobState.WAITING_FOR_USER,
                note=f"best={best_score:.2f}<{effective_threshold:.2f}",
            )
            self._engine.update_extra(
                job_id,
                {
                    **outcome_extra(
                        AcquisitionOutcomeCode.FOUND_BELOW_THRESHOLD,
                        detail=f"best {best_score:.0%} < {effective_threshold:.0%}",
                    ),
                    "below_threshold_attempts": below_attempts + 1,
                },
            )
            logger.info(
                "{}: best score {:.0%} below auto-acquire threshold {:.0%} — "
                "will keep searching (not parked in Review)",
                job_label(job),
                best_score,
                effective_threshold,
            )
            return RunnerOutcome(
                job_id,
                AcquisitionJobState.WAITING_FOR_USER,
                "below auto-acquire threshold",
                best_score=best_score,
                scored_count=len(scored),
            )

        outcome = self.start_download(
            job_id, best_result, auto_import=auto_import, score=best_score
        )
        if prior is not None and prior.scored_count:
            return RunnerOutcome(
                outcome.job_id,
                outcome.state,
                outcome.message,
                best_score=outcome.best_score,
                scored_count=prior.scored_count,
            )
        return outcome

    def start_download(
        self,
        job_id: UUID,
        result: SearchResult,
        *,
        auto_import: bool = True,
        score: float | None = None,
    ) -> RunnerOutcome:
        job = self._engine.get(job_id)
        if job is None:
            raise KeyError(f"AcquisitionJob {job_id} not found")

        if job.state not in (
            AcquisitionJobState.SCORING,
            AcquisitionJobState.WAITING_FOR_USER,
            AcquisitionJobState.COLLECTING_RESULTS,
            AcquisitionJobState.DOWNLOADING,
            AcquisitionJobState.DOWNLOAD_FAILED,
            AcquisitionJobState.VERIFICATION_FAILED,
            AcquisitionJobState.IMPORT_FAILED,
        ):
            raise ValueError(
                f"AcquisitionJob {job_id} cannot start download from {job.state.value}"
            )

        if job.state is AcquisitionJobState.COLLECTING_RESULTS:
            self._engine.advance(job_id, AcquisitionJobState.SCORING)
        elif job.state in (
            AcquisitionJobState.DOWNLOAD_FAILED,
            AcquisitionJobState.VERIFICATION_FAILED,
            AcquisitionJobState.IMPORT_FAILED,
        ):
            self._engine.advance(job_id, AcquisitionJobState.SCORING, note="try next peer")

        download_result = self._with_download_folder(job, result)
        attempted = [
            str(item) for item in (job.extra.get("attempted_result_ids") or []) if item
        ]
        if result.result_id not in attempted:
            attempted.append(result.result_id)
        self._engine.update_extra(
            job_id,
            {
                "attempted_result_ids": attempted,
                "selected_result_id": result.result_id,
                "selected_provider_id": result.provider_id,
                "selected_score": score,
            },
        )
        handle = self._downloads.start(job_id, download_result)
        if handle is None:
            loaded = self._engine.get(job_id)
            assert loaded is not None
            logger.warning("Download start failed for {}", job_label(loaded))
            self._engine.update_extra(
                job_id,
                outcome_extra(
                    AcquisitionOutcomeCode.FOUND_DOWNLOAD_FAILED,
                    detail="download start failed",
                ),
            )
            next_outcome = self._try_next_download_candidate(job_id, auto_import=auto_import)
            if next_outcome is not None:
                return next_outcome
            return RunnerOutcome(job_id, loaded.state, "download start failed")

        sibling_count = self._enqueue_album_siblings(job, download_result)
        label = job_label(job)
        logger.info(
            "Downloading {} via {} ({}) → {}{}",
            label,
            download_result.display_name,
            download_result.provider_id,
            download_result.raw.get("folder_path") or "(provider default folder)",
            f" (+{sibling_count} album sibling(s))" if sibling_count else "",
        )

        status = self._downloads.poll(job_id)
        if status is not None and status.state == "completed" and status.local_paths:
            logger.info("Download complete for {} — {} file(s)", label, len(status.local_paths))
            self._download_progress_logged.pop(job_id, None)
            self._workflow.finish_download(job_id, status.local_paths, auto_import=auto_import)
            loaded = self._engine.get(job_id)
            assert loaded is not None
            if loaded.state in (
                AcquisitionJobState.DOWNLOAD_FAILED,
                AcquisitionJobState.VERIFICATION_FAILED,
                AcquisitionJobState.IMPORT_FAILED,
            ):
                next_outcome = self._try_next_download_candidate(
                    job_id, auto_import=auto_import
                )
                if next_outcome is not None:
                    return next_outcome
            elif loaded.state is AcquisitionJobState.COMPLETED:
                self._engine.update_extra(
                    job_id,
                    outcome_extra(
                        AcquisitionOutcomeCode.ALREADY_OWNED
                        if (loaded.extra or {}).get("outcome_code") == "already_owned"
                        else AcquisitionOutcomeCode.ACQUIRED
                    ),
                )
            return RunnerOutcome(job_id, loaded.state, "download completed immediately")

        loaded = self._engine.get(job_id)
        assert loaded is not None
        return RunnerOutcome(
            job_id,
            loaded.state,
            "download started",
            best_score=score,
        )

    def start_download_by_result_id(
        self,
        job_id: UUID,
        result_id: str,
        *,
        auto_import: bool = True,
    ) -> RunnerOutcome:
        job = self._engine.get(job_id)
        if job is None:
            raise KeyError(f"AcquisitionJob {job_id} not found")
        result = _find_result(job, result_id)
        if result is None:
            raise KeyError(f"Search result {result_id} not found on job {job_id}")
        score = _score_for_result(job, result_id)
        return self.start_download(job_id, result, auto_import=auto_import, score=score)

    def poll_active_jobs(
        self,
        library_id: UUID | None = None,
        *,
        auto_import: bool = True,
    ) -> int:
        """Poll DOWNLOADING jobs; finish verify/import when complete."""
        downloading = [
            job
            for job in self._engine.list_jobs(library_id=library_id)
            if job.state is AcquisitionJobState.DOWNLOADING
        ]
        count = len(downloading)
        if count != self._last_active_download_count:
            if count:
                logger.info("{} download(s) in progress", count)
            elif self._last_active_download_count:
                logger.info("All active downloads finished")
            self._last_active_download_count = count

        updated = 0
        for job in downloading:
            status = self._downloads.poll(job.id)
            label = job_label(job)
            folder_paths = _audio_files_in_download_folder(job)

            # Files already on disk: finish even when the in-memory handle was
            # lost (app restart) or Nicotine transfer matching lags.
            if folder_paths and (
                status is None or status.state in ("queued", "downloading", "completed")
            ):
                if status is None or status.state == "completed" or _folder_has_ready_audio(
                    folder_paths
                ):
                    paths = list(status.local_paths) if status and status.local_paths else []
                    merged = {str(p): p for p in paths}
                    for path in folder_paths:
                        merged[str(path)] = path
                    paths = list(merged.values())
                    logger.info(
                        "Download complete for {} — {} file(s){}",
                        label,
                        len(paths),
                        " (recovered from folder)" if status is None else "",
                    )
                    self._download_progress_logged.pop(job.id, None)
                    self._workflow.finish_download(
                        job.id,
                        paths,
                        auto_import=auto_import,
                    )
                    self._after_download_finished(job.id, auto_import=auto_import)
                    updated += 1
                    continue

            if status is None:
                continue
            if status.state not in ("completed", "failed", "cancelled"):
                milestone = int((status.progress or 0.0) * 100) // 25 * 25
                last = self._download_progress_logged.get(job.id, -1)
                if milestone > last and milestone > 0:
                    self._download_progress_logged[job.id] = milestone
                    logger.info("Download {}% for {}", milestone, label)
            if status.state == "completed":
                paths = list(status.local_paths) if status.local_paths else None
                if folder_paths:
                    merged = {str(p): p for p in (paths or [])}
                    for path in folder_paths:
                        merged[str(path)] = path
                    paths = list(merged.values())
                if paths:
                    logger.info("Download complete for {} — {} file(s)", label, len(paths))
                self._download_progress_logged.pop(job.id, None)
                self._workflow.finish_download(
                    job.id,
                    paths,
                    auto_import=auto_import,
                )
                self._after_download_finished(job.id, auto_import=auto_import)
                updated += 1
            elif status.state in ("failed", "cancelled"):
                # Prefer folder recovery over a stale/sibling failure signal.
                if folder_paths and _folder_has_ready_audio(folder_paths):
                    logger.info(
                        "Download complete for {} — {} file(s) (folder override after {})",
                        label,
                        len(folder_paths),
                        status.state,
                    )
                    self._download_progress_logged.pop(job.id, None)
                    self._workflow.finish_download(
                        job.id,
                        folder_paths,
                        auto_import=auto_import,
                    )
                    self._after_download_finished(job.id, auto_import=auto_import)
                    updated += 1
                    continue
                code = classify_download_message(status.message)
                logger.warning(
                    "Download {} for {}: {} [{}]",
                    status.state,
                    label,
                    status.message or status.state,
                    code.value,
                )
                self._download_progress_logged.pop(job.id, None)
                self._downloads.complete(job.id)
                self._engine.update_extra(
                    job.id,
                    outcome_extra(code, detail=status.message or status.state),
                )
                next_outcome = self._try_next_download_candidate(
                    job.id, auto_import=auto_import
                )
                if next_outcome is None:
                    loaded = self._engine.get(job.id)
                    logger.info(
                        "{}: no more peer candidates after {} — will retry later",
                        label,
                        code.value,
                    )
                    # Do not park — schedule normal retry via automation.
                    self._park_attention(loaded, message=status.message or status.state)
                updated += 1
        return updated

    def _after_download_finished(self, job_id: UUID, *, auto_import: bool) -> None:
        loaded = self._engine.get(job_id)
        if loaded is None:
            return
        if loaded.state is AcquisitionJobState.COMPLETED:
            code = AcquisitionOutcomeCode.ALREADY_OWNED
            if (loaded.extra or {}).get("outcome_code") != "already_owned":
                code = AcquisitionOutcomeCode.ACQUIRED
            self._engine.update_extra(job_id, outcome_extra(code))
            return
        if loaded.state is AcquisitionJobState.VERIFICATION_FAILED:
            failures = tuple(
                part
                for part in (loaded.error_message or "").split(";")
                if part
            )
            code = classify_verification_failures(failures)
            self._engine.update_extra(
                job_id, outcome_extra(code, detail=loaded.error_message or "")
            )
            if self._try_next_download_candidate(job_id, auto_import=auto_import) is None:
                logger.info(
                    "{}: verification failed ({}) — will retry with a fresh search later",
                    job_label(loaded),
                    code.value,
                )
            return
        if loaded.state in (
            AcquisitionJobState.DOWNLOAD_FAILED,
            AcquisitionJobState.IMPORT_FAILED,
        ):
            code = classify_download_message(loaded.error_message)
            self._engine.update_extra(
                job_id, outcome_extra(code, detail=loaded.error_message or "")
            )
            if self._try_next_download_candidate(job_id, auto_import=auto_import) is None:
                logger.info(
                    "{}: {} — will retry later",
                    job_label(loaded),
                    code.value,
                )

    def _try_next_download_candidate(
        self,
        job_id: UUID,
        *,
        auto_import: bool = True,
    ) -> RunnerOutcome | None:
        """Start the next scored peer/result that has not been attempted yet."""
        job = self._engine.get(job_id)
        if job is None:
            return None
        if job.state not in (
            AcquisitionJobState.SCORING,
            AcquisitionJobState.WAITING_FOR_USER,
            AcquisitionJobState.DOWNLOAD_FAILED,
            AcquisitionJobState.VERIFICATION_FAILED,
            AcquisitionJobState.IMPORT_FAILED,
        ):
            return None

        attempted = {
            str(item) for item in (job.extra.get("attempted_result_ids") or []) if item
        }
        scored = _load_scored(job)
        for result, score in scored:
            if result.result_id in attempted:
                continue
            if score < self._threshold:
                continue
            logger.info(
                "{}: trying next peer/result {} (score {:.0%})",
                job_label(job),
                result.display_name,
                score,
            )
            return self.start_download(
                job_id, result, auto_import=auto_import, score=score
            )
        return None

    def _with_download_folder(self, job: AcquisitionJob, result: SearchResult) -> SearchResult:
        """Point Nicotine downloads into Incoming/vaultseek-nicotine/<job_id>."""
        if self._libraries is None:
            return result
        library = self._libraries.get(job.library_id)
        if library is None or not library.incoming_path:
            return result
        folder = Path(library.incoming_path) / "vaultseek-nicotine" / str(job.id)
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError:
            logger.warning("Could not create Nicotine download folder {}", folder)
            return result
        raw = dict(result.raw)
        raw["folder_path"] = str(folder)
        self._engine.update_extra(job.id, {"nicotine_download_folder": str(folder)})
        return replace(result, raw=raw)

    def _enqueue_album_siblings(self, job: AcquisitionJob, primary: SearchResult) -> int:
        """Queue other files from the same peer folder when whole-album mode is on."""
        if not self._acquisition_config.download_whole_album_on_upgrade:
            return 0
        if job.job_type not in (
            AcquisitionJobType.QUALITY_UPGRADE,
            AcquisitionJobType.MISSING_ALBUM,
            AcquisitionJobType.MISSING_TRACK,
        ):
            return 0
        primary_key = _result_folder_key(primary)
        if not primary_key:
            return 0
        folder = primary.raw.get("folder_path")
        count = 0
        for item in job.extra.get("search_results") or []:
            if not isinstance(item, dict):
                continue
            sibling = _result_from_dict(item)
            if sibling.result_id == primary.result_id:
                continue
            if _result_folder_key(sibling) != primary_key:
                continue
            if not _is_audio_search_result(sibling):
                continue
            raw = dict(sibling.raw)
            if folder:
                raw["folder_path"] = str(folder)
            try:
                self._downloads._providers.download(  # noqa: SLF001
                    replace(sibling, raw=raw)
                )
                count += 1
            except Exception:
                logger.debug("Sibling enqueue skipped for {}", sibling.result_id)
            if count >= 40:
                break
        if count:
            self._engine.update_extra(job.id, {"album_sibling_enqueues": count})
        return count

    def _park_attention(
        self,
        job: AcquisitionJob | None,
        *,
        message: str = "",
        provider_offline: bool = False,
    ) -> None:
        park_if_attention_needed(
            self._reviews,
            job,
            message=message,
            provider_offline=provider_offline,
        )


_AUDIO_SUFFIXES = {".flac", ".mp3", ".m4a", ".aac", ".ogg", ".opus", ".wav", ".aiff", ".wma"}


def _is_audio_search_result(result: SearchResult) -> bool:
    raw = result.raw or {}
    candidates = [
        result.format,
        raw.get("extension"),
        raw.get("format"),
        result.display_name,
        raw.get("file_path"),
        raw.get("virtual_path"),
    ]
    for value in candidates:
        if not value:
            continue
        text = str(value).casefold()
        if text.lstrip(".") in {suffix.lstrip(".") for suffix in _AUDIO_SUFFIXES}:
            return True
        for suffix in _AUDIO_SUFFIXES:
            if text.endswith(suffix):
                return True
    return False


def _result_folder_key(result: SearchResult) -> str | None:
    raw = result.raw or {}
    path = str(raw.get("file_path") or raw.get("virtual_path") or result.display_name or "")
    if not path:
        return None
    normalized = path.replace("\\", "/")
    if "/" not in normalized:
        return None
    parent = normalized.rsplit("/", 1)[0]
    user = str(result.source_user or raw.get("username") or "")
    return f"{user}:{parent}".casefold() if parent else None


def _audio_files_in_download_folder(job: AcquisitionJob) -> list[Path]:
    folder_raw = job.extra.get("nicotine_download_folder")
    if not folder_raw:
        return []
    folder = Path(str(folder_raw))
    if not folder.is_dir():
        return []
    files: list[Path] = []
    try:
        for path in folder.rglob("*"):
            if path.is_file() and path.suffix.casefold() in _AUDIO_SUFFIXES:
                files.append(path)
    except OSError:
        return []
    return files


def _folder_has_ready_audio(paths: list[Path]) -> bool:
    """True when at least one non-empty audio file is present (download landed)."""
    for path in paths:
        try:
            if path.is_file() and path.stat().st_size > 0:
                return True
        except OSError:
            continue
    return False


def _result_to_dict(result: SearchResult) -> dict[str, Any]:
    return {
        "provider_id": result.provider_id,
        "result_id": result.result_id,
        "display_name": result.display_name,
        "artist": result.artist,
        "album": result.album,
        "title": result.title,
        "year": result.year,
        "format": result.format,
        "bit_depth": result.bit_depth,
        "sample_rate": result.sample_rate,
        "size_bytes": result.size_bytes,
        "track_count": result.track_count,
        "source_user": result.source_user,
        "raw": dict(result.raw),
    }


def _result_from_dict(data: dict[str, Any]) -> SearchResult:
    return SearchResult(
        provider_id=str(data["provider_id"]),
        result_id=str(data["result_id"]),
        display_name=str(data.get("display_name") or data["result_id"]),
        artist=data.get("artist"),
        album=data.get("album"),
        title=data.get("title"),
        year=data.get("year"),
        format=data.get("format"),
        bit_depth=data.get("bit_depth"),
        sample_rate=data.get("sample_rate"),
        size_bytes=data.get("size_bytes"),
        track_count=data.get("track_count"),
        source_user=data.get("source_user"),
        raw=dict(data.get("raw") or {}),
    )


def _load_scored(job: AcquisitionJob) -> list[tuple[SearchResult, float]]:
    by_id = {
        str(item["result_id"]): _result_from_dict(item)
        for item in job.extra.get("search_results") or []
        if isinstance(item, dict) and item.get("result_id")
    }
    scored: list[tuple[SearchResult, float]] = []
    for row in job.extra.get("scored_results") or []:
        if not isinstance(row, dict):
            continue
        result = by_id.get(str(row.get("result_id")))
        if result is None:
            continue
        scored.append((result, float(row.get("score") or 0.0)))
    scored.sort(key=lambda item: item[1], reverse=True)
    return scored


def _find_result(job: AcquisitionJob, result_id: str) -> SearchResult | None:
    for item in job.extra.get("search_results") or []:
        if isinstance(item, dict) and str(item.get("result_id")) == result_id:
            return _result_from_dict(item)
    return None


def _score_for_result(job: AcquisitionJob, result_id: str) -> float | None:
    for row in job.extra.get("scored_results") or []:
        if isinstance(row, dict) and str(row.get("result_id")) == result_id:
            return float(row.get("score") or 0.0)
    return None
