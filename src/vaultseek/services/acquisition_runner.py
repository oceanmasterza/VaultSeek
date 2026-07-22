"""AcquisitionRunner — search, score, auto-acquire, and poll active downloads."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from loguru import logger

from vaultseek.models.entities.acquisition_job import AcquisitionJob, AcquisitionJobState
from vaultseek.models.interfaces.acquisition import SearchResult
from vaultseek.services.acquisition_attention import park_if_attention_needed
from vaultseek.services.acquisition_engine import AcquisitionEngine
from vaultseek.services.acquisition_labels import job_label
from vaultseek.services.acquisition_workflow import AcquisitionWorkflow
from vaultseek.services.download_manager import DownloadManager
from vaultseek.services.review_queue_service import ReviewQueueService
from vaultseek.services.scoring_engine import ScoringEngine
from vaultseek.services.search_dispatcher import SearchDispatcher


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
    ) -> None:
        self._engine = acquisition_engine
        self._search = search_dispatcher
        self._scoring = scoring_engine
        self._downloads = download_manager
        self._workflow = acquisition_workflow
        self._threshold = auto_acquire_threshold
        self._reviews = review_queue
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

        if job.state is AcquisitionJobState.NO_RESULTS or not results:
            provider_offline = bool(job.extra.get("provider_offline"))
            message = (
                "no acquisition providers connected"
                if provider_offline
                else "no provider results"
            )
            logger.warning("Search for {}: {}", job_label(job), message)
            self._park_attention(job, message=message, provider_offline=provider_offline)
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
        outcome = self.search_and_score(job_id)
        job = self._engine.get(job_id)
        if job is None:
            raise KeyError(f"AcquisitionJob {job_id} not found")

        if job.state is AcquisitionJobState.NO_RESULTS:
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

        if job.state in (AcquisitionJobState.CREATED, AcquisitionJobState.QUEUED):
            return self.try_auto_acquire(job_id, auto_import=auto_import)

        if job.state is AcquisitionJobState.SCORING:
            return self._auto_acquire_from_scored(job_id, auto_import=auto_import)

        return None

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

        scored = _load_scored(job)
        if not scored:
            self._engine.advance(job_id, AcquisitionJobState.NO_RESULTS, note="nothing to score")
            job = self._engine.get(job_id)
            assert job is not None
            self._park_attention(job, message="no scored results")
            return RunnerOutcome(job_id, AcquisitionJobState.NO_RESULTS, "no scored results")

        best_result, best_score = scored[0]
        if best_score < self._threshold:
            self._engine.advance(
                job_id,
                AcquisitionJobState.WAITING_FOR_USER,
                note=f"best={best_score:.2f}<{self._threshold:.2f}",
            )
            logger.info(
                "{}: best score {:.0%} below auto-acquire threshold {:.0%}",
                job_label(job),
                best_score,
                self._threshold,
            )
            loaded = self._engine.get(job_id)
            self._park_attention(
                loaded,
                message=f"best score {best_score:.0%} below threshold {self._threshold:.0%}",
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
        ):
            raise ValueError(
                f"AcquisitionJob {job_id} cannot start download from {job.state.value}"
            )

        if job.state is AcquisitionJobState.COLLECTING_RESULTS:
            self._engine.advance(job_id, AcquisitionJobState.SCORING)

        handle = self._downloads.start(job_id, result)
        if handle is None:
            loaded = self._engine.get(job_id)
            assert loaded is not None
            logger.warning("Download start failed for {}", job_label(loaded))
            self._park_attention(loaded, message="download start failed")
            return RunnerOutcome(job_id, loaded.state, "download start failed")

        label = job_label(job)
        logger.info(
            "Downloading {} via {} ({})",
            label,
            result.display_name,
            result.provider_id,
        )

        self._engine.update_extra(
            job_id,
            {
                "selected_result_id": result.result_id,
                "selected_provider_id": result.provider_id,
                "selected_score": score,
            },
        )

        status = self._downloads.poll(job_id)
        if status is not None and status.state == "completed" and status.local_paths:
            logger.info("Download complete for {} — {} file(s)", label, len(status.local_paths))
            self._download_progress_logged.pop(job_id, None)
            self._workflow.finish_download(job_id, status.local_paths, auto_import=auto_import)
            loaded = self._engine.get(job_id)
            assert loaded is not None
            self._park_attention(loaded)
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
            if status is None:
                continue
            label = job_label(job)
            if status.state not in ("completed", "failed", "cancelled"):
                milestone = int((status.progress or 0.0) * 100) // 25 * 25
                last = self._download_progress_logged.get(job.id, -1)
                if milestone > last and milestone > 0:
                    self._download_progress_logged[job.id] = milestone
                    logger.info("Download {}% for {}", milestone, label)
            if status.state == "completed":
                paths = list(status.local_paths) if status.local_paths else None
                if paths:
                    logger.info("Download complete for {} — {} file(s)", label, len(paths))
                self._download_progress_logged.pop(job.id, None)
                self._workflow.finish_download(
                    job.id,
                    paths,
                    auto_import=auto_import,
                )
                loaded = self._engine.get(job.id)
                self._park_attention(loaded)
                updated += 1
            elif status.state in ("failed", "cancelled"):
                logger.warning(
                    "Download {} for {}: {}",
                    status.state,
                    label,
                    status.message or status.state,
                )
                self._download_progress_logged.pop(job.id, None)
                self._downloads.complete(job.id)
                loaded = self._engine.get(job.id)
                self._park_attention(loaded, message=status.message or status.state)
                updated += 1
        return updated

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
