"""Nicotine+ acquisition provider — socket or HTTP RPC transports."""

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
from loguru import logger

from vaultseek.plugins.builtin.nicotine_plus.http_api_rpc import HttpApiRpcClient
from vaultseek.plugins.builtin.nicotine_plus.rpc import (
    FakeRpcClient,
    LocalSocketRpcClient,
    NicotinePlusRpcClient,
    hits_to_search_results,
)
from vaultseek.plugins.builtin.nicotine_plus.search_rate_gate import (
    DEFAULT_SEARCH_RATE_GATE,
    SearchRateGate,
    SearchThrottled,
)


class NicotinePlusProvider:
    """Provider that probes Nicotine+ availability and delegates to an RPC client.

  Default transport is :class:`LocalSocketRpcClient` (VaultSeek NDJSON).
  Set ``transport=http`` in config for api-nicotine-plus on port 12339.
    """

    provider_id = "nicotine_plus"
    display_name = "Nicotine+"

    def __init__(
        self,
        *,
        connect_timeout_seconds: float = 1.0,
        rpc_client: NicotinePlusRpcClient | None = None,
        search_rate_gate: SearchRateGate | None = None,
    ) -> None:
        self._connect_timeout = connect_timeout_seconds
        self._rpc: NicotinePlusRpcClient = rpc_client or LocalSocketRpcClient(
            timeout_seconds=connect_timeout_seconds
        )
        self._injected = rpc_client is not None
        self._connected = False
        self._settings: dict[str, Any] = {}
        self._search_gate = search_rate_gate or DEFAULT_SEARCH_RATE_GATE

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
        """Replace the RPC transport (tests / alternate clients)."""
        self._rpc = client
        self._injected = True

    def connect(self, config: AcquisitionProviderConfig) -> bool:
        if not config.enabled:
            self._connected = False
            return False
        settings = dict(config.settings)
        host = str(settings.get("host") or "127.0.0.1")
        port = int(settings.get("port") or 22024)
        transport = str(settings.get("transport") or "socket").casefold()
        api_port = int(settings.get("api_port") or 12339)
        api_token = str(settings.get("api_token") or settings.get("password") or "")
        self._settings = settings
        self._search_gate.configure(
            min_interval_seconds=float(settings.get("search_min_interval_seconds") or 5.0),
            max_per_minute=int(settings.get("search_max_per_minute") or 8),
        )

        if not self._injected:
            if transport == "http":
                self._rpc = HttpApiRpcClient(
                    host=host,
                    port=api_port,
                    api_token=api_token,
                    timeout_seconds=self._connect_timeout,
                )
            else:
                self._rpc = LocalSocketRpcClient(
                    host=host,
                    port=port,
                    timeout_seconds=self._connect_timeout,
                )
        elif isinstance(self._rpc, LocalSocketRpcClient):
            self._rpc.configure(host, port, timeout_seconds=self._connect_timeout)
        elif isinstance(self._rpc, HttpApiRpcClient):
            self._rpc.configure(host, api_port, api_token=api_token, timeout_seconds=self._connect_timeout)

        if isinstance(self._rpc, FakeRpcClient):
            self._connected = True
            return True

        if isinstance(self._rpc, HttpApiRpcClient):
            self._connected = self._rpc.probe()
            return self._connected

        self._connected = self._probe_host(host, port)
        return self._connected

    def disconnect(self) -> None:
        self._connected = False
        self._settings = {}

    def search(self, request: SearchRequest) -> list[SearchResult]:
        if not self._connected:
            logger.warning("Nicotine+ search skipped — provider not connected")
            return []
        query = " ".join(p for p in (request.artist, request.album, request.title) if p)
        transport = str(self._settings.get("transport") or "socket")
        # Fake RPC is unit-test only — never wait on the Soulseek flood gate.
        if not isinstance(self._rpc, FakeRpcClient):
            delay = self._search_gate.try_acquire()
            if delay is not None:
                logger.info(
                    "Nicotine+ search deferred {:.1f}s (min {}s, max {}/min): {}",
                    delay,
                    self._search_gate.min_interval_seconds,
                    self._search_gate.max_per_minute,
                    query or "(empty query)",
                )
                raise SearchThrottled(delay)
        logger.info("Nicotine+ search via {}: {}", transport, query or "(empty query)")
        wait_seconds = float(self._settings.get("search_timeout_seconds") or 30.0)
        if isinstance(self._rpc, HttpApiRpcClient):
            hits = self._rpc.search(request, wait_seconds=wait_seconds)
        else:
            hits = self._rpc.search(request)
        results = hits_to_search_results(hits)
        logger.info("Nicotine+ returned {} hit(s) for {}", len(results), query or "(empty query)")
        return results

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
