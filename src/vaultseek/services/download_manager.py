"""DownloadManager — queue and track acquisition downloads."""

from __future__ import annotations

from pathlib import Path
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

    def complete(
        self,
        job_id: UUID,
        local_paths: list[Path] | tuple[Path, ...] | None = None,
    ) -> DownloadStatus | None:
        """Persist paths and advance DOWNLOADING → VERIFYING when ready.

        If ``local_paths`` is omitted, uses paths from the latest provider status.
        Failed provider status advances to DOWNLOAD_FAILED.
        """
        job = self._engine.get(job_id)
        if job is None:
            raise KeyError(f"AcquisitionJob {job_id} not found")
        if job.state is not AcquisitionJobState.DOWNLOADING:
            raise ValueError(
                f"AcquisitionJob {job_id} must be DOWNLOADING "
                f"(current: {job.state.value})"
            )

        status = self.poll(job_id)
        if local_paths is not None:
            paths = [Path(p) for p in local_paths]
        elif status is not None and status.local_paths:
            paths = list(status.local_paths)
        else:
            paths = []

        # Explicit paths allow completing even when provider status is stub/failed.
        if local_paths is not None and paths:
            self._engine.update_extra(job_id, {"local_paths": [str(p) for p in paths]})
            self._engine.advance(
                job_id,
                AcquisitionJobState.VERIFYING,
                note=f"{len(paths)} file(s)",
            )
            self._handles.pop(job_id, None)
            return status or DownloadStatus(
                download_id="manual",
                state="completed",
                progress=1.0,
                local_paths=tuple(paths),
            )

        if status is not None and status.state == "failed":
            self._engine.advance(
                job_id,
                AcquisitionJobState.DOWNLOAD_FAILED,
                note=status.message or "download failed",
            )
            self._handles.pop(job_id, None)
            return status

        if status is not None and status.state == "cancelled":
            self._engine.cancel(job_id)
            self._handles.pop(job_id, None)
            return status

        if status is not None and status.state == "completed":
            if not paths:
                self._engine.advance(
                    job_id,
                    AcquisitionJobState.DOWNLOAD_FAILED,
                    note="completed without local_paths",
                )
                self._handles.pop(job_id, None)
                return status
            self._engine.update_extra(job_id, {"local_paths": [str(p) for p in paths]})
            self._engine.advance(
                job_id,
                AcquisitionJobState.VERIFYING,
                note=f"{len(paths)} file(s)",
            )
            self._handles.pop(job_id, None)
            return status

        # Still in progress — no state change.
        return status

    def cancel(self, job_id: UUID) -> bool:
        handle = self._handles.pop(job_id, None)
        if handle is None:
            return False
        cancelled = self._providers.cancel(handle)
        self._engine.cancel(job_id)
        return cancelled
