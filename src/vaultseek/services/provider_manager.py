"""ProviderManager — sole gateway to acquisition providers."""

from __future__ import annotations

from collections.abc import Sequence

from vaultseek.models.interfaces.acquisition import (
    AcquisitionProvider,
    AcquisitionProviderConfig,
    DownloadHandle,
    DownloadStatus,
    SearchRequest,
    SearchResult,
)


class ProviderManager:
    """Registers, configures, and dispatches to acquisition providers."""

    def __init__(self, providers: Sequence[AcquisitionProvider] = ()) -> None:
        self._providers: dict[str, AcquisitionProvider] = {
            provider.provider_id: provider for provider in providers
        }
        self._connected: set[str] = set()

    def list_providers(self) -> list[AcquisitionProvider]:
        return list(self._providers.values())

    def get(self, provider_id: str) -> AcquisitionProvider | None:
        return self._providers.get(provider_id)

    def connect(self, config: AcquisitionProviderConfig) -> bool:
        provider = self._providers.get(config.provider_id)
        if provider is None or not config.enabled:
            return False
        ok = provider.connect(config)
        if ok:
            self._connected.add(config.provider_id)
        else:
            self._connected.discard(config.provider_id)
        return ok

    def disconnect(self, provider_id: str | None = None) -> None:
        ids = [provider_id] if provider_id else list(self._connected)
        for pid in ids:
            provider = self._providers.get(pid)
            if provider is not None:
                provider.disconnect()
            self._connected.discard(pid)

    def search(
        self,
        request: SearchRequest,
        *,
        provider_ids: Sequence[str] | None = None,
    ) -> list[SearchResult]:
        results: list[SearchResult] = []
        for provider in self._iter_active(provider_ids):
            if provider.capabilities.search:
                results.extend(provider.search(request))
        return results

    def download(self, result: SearchResult) -> DownloadHandle | None:
        provider = self._providers.get(result.provider_id)
        if provider is None or result.provider_id not in self._connected:
            return None
        if not provider.capabilities.download:
            return None
        return provider.download(result)

    def cancel(self, handle: DownloadHandle) -> bool:
        provider = self._providers.get(handle.provider_id)
        if provider is None:
            return False
        return provider.cancel(handle)

    def get_status(self, handle: DownloadHandle) -> DownloadStatus | None:
        provider = self._providers.get(handle.provider_id)
        if provider is None:
            return None
        return provider.get_status(handle)

    def _iter_active(
        self, provider_ids: Sequence[str] | None
    ) -> list[AcquisitionProvider]:
        if provider_ids is None:
            ids = list(self._connected)
        else:
            ids = [pid for pid in provider_ids if pid in self._connected]
        return [self._providers[pid] for pid in ids if pid in self._providers]
