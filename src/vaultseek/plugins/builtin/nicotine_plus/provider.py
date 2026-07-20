"""Nicotine+ acquisition provider — RPC-backed skeleton (Phase 4)."""

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
from vaultseek.plugins.builtin.nicotine_plus.rpc import (
    NicotinePlusRpcClient,
    UnimplementedRpcClient,
    hits_to_search_results,
)


class NicotinePlusProvider:
    """Provider that probes Nicotine+ availability and delegates to an RPC client.

    Default RPC client is a no-op stub. Tests (and a future real transport)
    inject a NicotinePlusRpcClient implementation.
    """

    provider_id = "nicotine_plus"
    display_name = "Nicotine+"

    def __init__(
        self,
        *,
        connect_timeout_seconds: float = 1.0,
        rpc_client: NicotinePlusRpcClient | None = None,
    ) -> None:
        self._connect_timeout = connect_timeout_seconds
        self._rpc: NicotinePlusRpcClient = rpc_client or UnimplementedRpcClient()
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

    @property
    def rpc_client(self) -> NicotinePlusRpcClient:
        return self._rpc

    def set_rpc_client(self, client: NicotinePlusRpcClient) -> None:
        """Replace the RPC transport (tests / future real client)."""
        self._rpc = client

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
        return hits_to_search_results(self._rpc.search(request))

    def download(self, result: SearchResult) -> DownloadHandle:
        download_id = self._rpc.enqueue_download(result.result_id, raw=dict(result.raw))
        return DownloadHandle(
            provider_id=self.provider_id,
            download_id=download_id,
            result_id=result.result_id,
        )

    def cancel(self, handle: DownloadHandle) -> bool:
        if not self._connected:
            return False
        return self._rpc.cancel(handle.download_id)

    def get_status(self, handle: DownloadHandle) -> DownloadStatus:
        if not self._connected:
            return DownloadStatus(
                download_id=handle.download_id,
                state="failed",
                progress=0.0,
                message="Nicotine+ is not connected.",
            )
        state = self._rpc.download_status(handle.download_id)
        return DownloadStatus(
            download_id=state.download_id,
            state=state.state,
            progress=state.progress,
            message=state.message,
            local_paths=state.local_paths,
        )

    def _probe_host(self, host: str, port: int) -> bool:
        try:
            with socket.create_connection((host, port), timeout=self._connect_timeout):
                return True
        except OSError:
            return False
