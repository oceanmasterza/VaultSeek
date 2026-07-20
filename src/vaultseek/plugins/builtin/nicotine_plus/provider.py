"""Nicotine+ acquisition provider — skeleton (Phase 4)."""

from __future__ import annotations

import socket
from typing import Any

from vaultseek.models.interfaces.acquisition import (
    AcquisitionProviderConfig,
    DownloadHandle,
    DownloadStatus,
    ProviderCapabilities,
    SearchRequest,
    SearchResult,
)


class NicotinePlusProvider:
    """Skeleton provider that probes Nicotine+ RPC availability.

    Does not implement Soulseek search/download yet — returns empty results
    and fails downloads gracefully when Nicotine+ is unavailable.
    """

    provider_id = "nicotine_plus"
    display_name = "Nicotine+"

    def __init__(self, *, connect_timeout_seconds: float = 1.0) -> None:
        self._connect_timeout = connect_timeout_seconds
        self._connected = False
        self._settings: dict[str, Any] = {}

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            search=True,
            browse=False,
            download=True,
            cancel=True,
            progress=True,
        )

    def connect(self, config: AcquisitionProviderConfig) -> bool:
        if not config.enabled:
            self._connected = False
            return False
        settings = dict(config.settings)
        host = str(settings.get("host") or "127.0.0.1")
        port = int(settings.get("port") or 22024)
        self._settings = settings
        self._connected = self._probe_host(host, port)
        return self._connected

    def disconnect(self) -> None:
        self._connected = False
        self._settings = {}

    def search(self, request: SearchRequest) -> list[SearchResult]:
        if not self._connected:
            return []
        return []

    def download(self, result: SearchResult) -> DownloadHandle:
        return DownloadHandle(
            provider_id=self.provider_id,
            download_id=f"nicotine-{result.result_id}",
            result_id=result.result_id,
        )

    def cancel(self, handle: DownloadHandle) -> bool:
        return self._connected

    def get_status(self, handle: DownloadHandle) -> DownloadStatus:
        if not self._connected:
            return DownloadStatus(
                download_id=handle.download_id,
                state="failed",
                progress=0.0,
                message="Nicotine+ is not connected.",
            )
        return DownloadStatus(
            download_id=handle.download_id,
            state="failed",
            progress=0.0,
            message="Nicotine+ download not implemented yet (Phase 4 skeleton).",
        )

    def _probe_host(self, host: str, port: int) -> bool:
        try:
            with socket.create_connection((host, port), timeout=self._connect_timeout):
                return True
        except OSError:
            return False
