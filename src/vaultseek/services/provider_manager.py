"""ProviderManager — sole gateway to acquisition providers."""

from __future__ import annotations

import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from threading import RLock

from loguru import logger

from vaultseek.models.interfaces.acquisition import (
    AcquisitionProvider,
    AcquisitionProviderConfig,
    DownloadHandle,
    DownloadStatus,
    SearchRequest,
    SearchResult,
)
from vaultseek.plugins.builtin.nicotine_plus.search_rate_gate import SearchThrottleError

_LEGACY_PROWLARR = frozenset({"prowlarr", "prowlarr_qbit"})
_PROWLARR_SPLIT = ("usenet", "prowlarr_public", "prowlarr_private")


def _normalize_order_id(provider_id: str) -> list[str]:
    if provider_id in _LEGACY_PROWLARR:
        return list(_PROWLARR_SPLIT)
    return [provider_id]


class ProviderManager:
    """Registers, configures, and dispatches to acquisition providers.

    Connect / disconnect / search / download share one reentrant lock so
    Settings and Plugins background reconnects cannot mutate providers while
    a search (or another reconnect) is in flight.

    GUI status reads use immutable snapshots published after mutations so the
    UI never waits on network I/O or waterfall sleeps held under that lock.
    """

    def __init__(
        self,
        providers: Sequence[AcquisitionProvider] = (),
        *,
        provider_order: Sequence[str] | None = None,
        search_waterfall: bool = True,
        provider_search_delay_seconds: float = 15.0,
    ) -> None:
        self._providers: dict[str, AcquisitionProvider] = {
            provider.provider_id: provider for provider in providers
        }
        self._connected: set[str] = set()
        self._provider_order: tuple[str, ...] = tuple(provider_order or ())
        self._search_waterfall = search_waterfall
        self._provider_search_delay_seconds = max(0.0, float(provider_search_delay_seconds))
        self._lifecycle_lock = RLock()
        # Lock-free GUI status: reference swaps of immutable frozenset/tuple.
        self._connected_snapshot: frozenset[str] = frozenset()
        self._provider_order_snapshot: tuple[str, ...] = self._provider_order

    def _publish_status_snapshot(self) -> None:
        """Publish connected/order views for lock-free GUI status reads."""
        self._connected_snapshot = frozenset(self._connected)
        self._provider_order_snapshot = self._provider_order

    @contextmanager
    def lifecycle(self) -> Iterator[None]:
        """Hold the provider lifecycle lock for a multi-step reconnect."""
        with self._lifecycle_lock:
            yield

    def set_provider_order(self, order: Sequence[str]) -> None:
        """Prefer this order when searching (e.g. config.provider_order)."""
        expanded: list[str] = []
        for pid in order:
            for part in _normalize_order_id(pid):
                if part not in expanded:
                    expanded.append(part)
        with self._lifecycle_lock:
            self._provider_order = tuple(expanded)
            self._publish_status_snapshot()

    def set_search_waterfall(
        self,
        *,
        enabled: bool,
        delay_seconds: float | None = None,
    ) -> None:
        """Configure stop-after-first-hits and inter-tier delay."""
        with self._lifecycle_lock:
            self._search_waterfall = bool(enabled)
            if delay_seconds is not None:
                self._provider_search_delay_seconds = max(0.0, float(delay_seconds))

    def list_providers(self) -> list[AcquisitionProvider]:
        return list(self._providers.values())

    def connected_provider_ids(self) -> tuple[str, ...]:
        """Ids of providers that successfully connected.

        Reads an immutable snapshot — never waits on connect/search network I/O.
        """
        return tuple(sorted(self._connected_snapshot))

    def has_connected_search_providers(self, *, provider_ids: Sequence[str] | None = None) -> bool:
        """True when at least one real (non-stub) connected provider can search.

        Reads immutable snapshots — never waits on connect/search network I/O.
        """
        return any(
            provider.capabilities.search and provider.provider_id != "stub"
            for provider in self._iter_active_from(
                self._connected_snapshot,
                self._provider_order_snapshot,
                provider_ids,
            )
        )

    def get(self, provider_id: str) -> AcquisitionProvider | None:
        return self._providers.get(provider_id)

    def connect(self, config: AcquisitionProviderConfig) -> bool:
        with self._lifecycle_lock:
            provider = self._providers.get(config.provider_id)
            if provider is None or not config.enabled:
                return False
            ok = provider.connect(config)
            if ok:
                self._connected.add(config.provider_id)
            else:
                self._connected.discard(config.provider_id)
            self._publish_status_snapshot()
            return ok

    def disconnect(self, provider_id: str | None = None) -> None:
        with self._lifecycle_lock:
            ids = [provider_id] if provider_id else list(self._connected)
            for pid in ids:
                if pid is None:
                    continue
                provider = self._providers.get(pid)
                if provider is not None:
                    provider.disconnect()
                self._connected.discard(pid)
            self._publish_status_snapshot()

    def search(
        self,
        request: SearchRequest,
        *,
        provider_ids: Sequence[str] | None = None,
    ) -> list[SearchResult]:
        with self._lifecycle_lock:
            return self._search_locked(request, provider_ids=provider_ids)

    def _search_locked(
        self,
        request: SearchRequest,
        *,
        provider_ids: Sequence[str] | None = None,
    ) -> list[SearchResult]:
        results: list[SearchResult] = []
        connection_errors: list[ConnectionError] = []
        throttled: SearchThrottleError | None = None
        active = self._iter_active(provider_ids)
        for index, provider in enumerate(active):
            if not provider.capabilities.search:
                continue
            try:
                batch = provider.search(request)
            except SearchThrottleError as exc:
                # Nicotine flood gate must not block later waterfall tiers.
                throttled = exc
                logger.info(
                    "Provider {} deferred ({:.1f}s) — continuing with other providers",
                    provider.provider_id,
                    exc.retry_after_seconds,
                )
                continue
            except ConnectionError as exc:
                connection_errors.append(exc)
                logger.warning(
                    "Provider {} communication error: {}",
                    provider.provider_id,
                    exc,
                )
                continue
            logger.debug(
                "Provider {} returned {} result(s)",
                provider.provider_id,
                len(batch),
            )
            if batch:
                results.extend(batch)
                if self._search_waterfall:
                    logger.info(
                        "Search waterfall stopping after {} ({} hit(s))",
                        provider.provider_id,
                        len(batch),
                    )
                    return results
                continue
            # Empty tier: optionally wait before the next source so a slow
            # previous search is less likely to still be "in flight" for the UX
            # (and so bulk wishlist passes do not hammer every backend at once).
            if (
                self._search_waterfall
                and self._provider_search_delay_seconds > 0
                and index < len(active) - 1
            ):
                logger.debug(
                    "No hits from {}; waiting {:.1f}s before next search source",
                    provider.provider_id,
                    self._provider_search_delay_seconds,
                )
                time.sleep(self._provider_search_delay_seconds)
        if results:
            return results
        if throttled is not None and not connection_errors:
            raise throttled
        if connection_errors:
            raise connection_errors[0]
        return results

    def download(self, result: SearchResult) -> DownloadHandle | None:
        with self._lifecycle_lock:
            provider = self._providers.get(result.provider_id)
            if provider is None or result.provider_id not in self._connected:
                return None
            if not provider.capabilities.download:
                return None
            return provider.download(result)

    def cancel(self, handle: DownloadHandle) -> bool:
        with self._lifecycle_lock:
            provider = self._providers.get(handle.provider_id)
            if provider is None:
                return False
            return provider.cancel(handle)

    def get_status(self, handle: DownloadHandle) -> DownloadStatus | None:
        with self._lifecycle_lock:
            provider = self._providers.get(handle.provider_id)
            if provider is None:
                return None
            return provider.get_status(handle)

    def _iter_active(self, provider_ids: Sequence[str] | None) -> list[AcquisitionProvider]:
        return self._iter_active_from(self._connected, self._provider_order, provider_ids)

    def _iter_active_from(
        self,
        connected: set[str] | frozenset[str],
        provider_order: Sequence[str],
        provider_ids: Sequence[str] | None,
    ) -> list[AcquisitionProvider]:
        if provider_ids is None:
            preferred: list[str] = []
            for pid in provider_order:
                for part in _normalize_order_id(pid):
                    if part not in preferred:
                        preferred.append(part)
            ordered = [pid for pid in preferred if pid in connected]
            ordered.extend(pid for pid in sorted(connected) if pid not in ordered)
            ids = ordered
        else:
            ids = []
            for pid in provider_ids:
                for part in _normalize_order_id(pid):
                    if part in connected and part not in ids:
                        ids.append(part)
        return [self._providers[pid] for pid in ids if pid in self._providers]
