"""DownloadManager — queue and track acquisition downloads."""

from __future__ import annotations

from uuid import UUID

from vaultseek.models.entities.acquisition_job import AcquisitionJobState
from vaultseek.models.interfaces.acquisition import DownloadHandle, DownloadStatus, SearchResult
from vaultseek.services.acquisition_engine import AcquisitionEngine
from vaultseek.services.provider_manager import ProviderManager


class DownloadManager:
    """Skeleton download manager — delegates to ProviderManager."""

    def __init__(
        self,
        provider_manager: ProviderManager,
        acquisition_engine: AcquisitionEngine,
    ) -> None:
        self._providers = provider_manager
        self._engine = acquisition_engine
        self._handles: dict[UUID, DownloadHandle] = {}

    def start(self, job_id: UUID, result: SearchResult) -> DownloadHandle | None:
        job = self._engine.get(job_id)
        if job is None:
            raise KeyError(f"AcquisitionJob {job_id} not found")

        handle = self._providers.download(result)
        if handle is None:
            self._engine.advance(
                job_id,
                AcquisitionJobState.DOWNLOAD_FAILED,
                note=f"provider {result.provider_id} unavailable",
            )
            return None

        self._handles[job_id] = handle
        self._engine.advance(
            job_id,
            AcquisitionJobState.DOWNLOADING,
            note=f"{result.provider_id}:{result.result_id}",
        )
        return handle

    def poll(self, job_id: UUID) -> DownloadStatus | None:
        handle = self._handles.get(job_id)
        if handle is None:
            return None
        return self._providers.get_status(handle)

    def cancel(self, job_id: UUID) -> bool:
        handle = self._handles.pop(job_id, None)
        if handle is None:
            return False
        cancelled = self._providers.cancel(handle)
        self._engine.cancel(job_id)
        return cancelled
