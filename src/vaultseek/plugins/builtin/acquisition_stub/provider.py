"""Stub acquisition provider — Phase 1 placeholder (no network I/O)."""

from __future__ import annotations

from vaultseek.models.interfaces.acquisition import (
    AcquisitionProviderConfig,
    DownloadHandle,
    DownloadStatus,
    ProviderCapabilities,
    SearchRequest,
    SearchResult,
)


class StubAcquisitionProvider:
    """No-op acquisition provider used to wire the Provider Framework."""

    provider_id = "stub"
    display_name = "Stub (Phase 1 placeholder)"

    def __init__(self) -> None:
        self._connected = False

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            search=True,
            browse=False,
            download=True,
            cancel=True,
            progress=False,
        )

    def connect(self, config: AcquisitionProviderConfig) -> bool:
        self._connected = bool(config.enabled)
        return self._connected

    def disconnect(self) -> None:
        self._connected = False

    def search(self, request: SearchRequest) -> list[SearchResult]:
        return []

    def download(self, result: SearchResult) -> DownloadHandle:
        return DownloadHandle(
            provider_id=self.provider_id,
            download_id=f"stub-{result.result_id}",
            result_id=result.result_id,
        )

    def cancel(self, handle: DownloadHandle) -> bool:
        return True

    def get_status(self, handle: DownloadHandle) -> DownloadStatus:
        return DownloadStatus(
            download_id=handle.download_id,
            state="failed",
            progress=0.0,
            message="Stub provider does not download (Phase 1 placeholder).",
        )
