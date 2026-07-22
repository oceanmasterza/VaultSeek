"""SearchDispatcher — provider-independent search dispatch for AcquisitionJobs."""

from __future__ import annotations

from uuid import UUID

from loguru import logger

from vaultseek.models.entities.acquisition_job import AcquisitionJobState
from vaultseek.models.interfaces.acquisition import SearchRequest, SearchResult
from vaultseek.plugins.builtin.nicotine_plus.search_rate_gate import SearchThrottled
from vaultseek.services.acquisition_engine import AcquisitionEngine
from vaultseek.services.acquisition_labels import job_label
from vaultseek.services.provider_manager import ProviderManager


class SearchDispatcher:
    """Build SearchRequests from jobs and dispatch to connected providers."""

    def __init__(
        self,
        provider_manager: ProviderManager,
        acquisition_engine: AcquisitionEngine,
        *,
        timeout_seconds: float = 30.0,
    ) -> None:
        self._providers = provider_manager
        self._engine = acquisition_engine
        self._timeout_seconds = timeout_seconds

    @property
    def timeout_seconds(self) -> float:
        return self._timeout_seconds

    def build_request(self, job_id: UUID) -> SearchRequest:
        job = self._engine.get(job_id)
        if job is None:
            raise KeyError(f"AcquisitionJob {job_id} not found")
        return SearchRequest(
            artist=job.artist,
            album=job.album,
            title=job.title,
            year=job.year,
            preferred_format=job.preferred_codec,
            extra={"mb_release_id": job.mb_release_id or ""},
        )

    def dispatch(self, job_id: UUID) -> list[SearchResult]:
        """Advance job to SEARCHING, query providers, then COLLECTING_RESULTS."""
        job = self._engine.get(job_id)
        if job is None:
            raise KeyError(f"AcquisitionJob {job_id} not found")

        if job.state is AcquisitionJobState.CREATED:
            self._engine.queue(job_id)
            job = self._engine.get(job_id)
            assert job is not None

        if job.state is AcquisitionJobState.QUEUED:
            self._engine.advance(job_id, AcquisitionJobState.SEARCHING)
            job = self._engine.get(job_id)
            assert job is not None

        request = SearchRequest(
            artist=job.artist,
            album=job.album,
            title=job.title,
            year=job.year,
            preferred_format=job.preferred_codec,
            extra={"mb_release_id": job.mb_release_id or ""},
        )
        provider_ids = job.preferred_providers or None

        if not self._providers.has_connected_search_providers(provider_ids=provider_ids):
            note = "no acquisition providers connected (offline or disabled)"
            logger.warning("Search for {}: {}", job_label(job), note)
            self._engine.advance(job_id, AcquisitionJobState.NO_RESULTS, note=note)
            self._engine.update_extra(job_id, {"provider_offline": True})
            return []

        logger.info("Searching providers for {}", job_label(job))
        try:
            results = self._providers.search(request, provider_ids=provider_ids)
        except SearchThrottled as exc:
            logger.info(
                "Search for {} deferred ({:.1f}s) to avoid Soulseek flood ban",
                job_label(job),
                exc.retry_after_seconds,
            )
            # Roll back to QUEUED so automation retries after the rate window.
            if job.state is AcquisitionJobState.SEARCHING:
                self._engine.advance(
                    job_id,
                    AcquisitionJobState.QUEUED,
                    note=f"rate-limited {exc.retry_after_seconds:.1f}s",
                )
            self._engine.update_extra(
                job_id,
                {
                    "provider_offline": False,
                    "search_deferred": True,
                    "search_retry_after_seconds": exc.retry_after_seconds,
                },
            )
            return []

        if not results:
            logger.info("Search for {}: no provider results", job_label(job))
            self._engine.advance(
                job_id,
                AcquisitionJobState.NO_RESULTS,
                note="no provider results",
            )
            self._engine.update_extra(job_id, {"provider_offline": False})
            return []

        logger.info("Search found {} result(s) for {}", len(results), job_label(job))

        self._engine.advance(
            job_id,
            AcquisitionJobState.COLLECTING_RESULTS,
            note=f"{len(results)} result(s)",
        )
        self._engine.update_extra(job_id, {"provider_offline": False})
        return results
