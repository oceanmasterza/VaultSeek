"""Round-robin AcoustID pool — multiple API keys and optional HTTP proxies.

Each endpoint is rate-limited independently (3 req/s per AcoustID guidelines),
so three keys on three proxies can sustain ~9 lookups/sec combined.
"""

from __future__ import annotations

import itertools
import threading
from typing import Any, Literal

from loguru import logger

from vaultseek.models.interfaces.metadata import MetadataQuery, ProviderResult
from vaultseek.plugins.builtin.acoustid.provider import AcoustIdProvider


class AcoustIdProviderPool:
    """Single metadata provider facade over multiple AcoustID endpoints."""

    provider_id = "acoustid"
    priority = 5
    plugin_id = "acoustid"

    def __init__(self, endpoints: list[AcoustIdProvider]) -> None:
        if not endpoints:
            raise ValueError("AcoustIdProviderPool requires at least one endpoint")
        self._endpoints = endpoints
        self._cycle = itertools.cycle(range(len(endpoints)))
        self._pick_lock = threading.Lock()
        labels = [endpoint.label for endpoint in endpoints]
        logger.info(
            "AcoustID pool ready: {} endpoint(s) — {}",
            len(endpoints),
            ", ".join(labels),
        )

    def lookup_by_fingerprint(self, fingerprint: bytes, duration: float) -> ProviderResult | None:
        endpoint = self._next_endpoint()
        if endpoint is None:
            return None
        return endpoint.lookup_by_fingerprint(fingerprint, duration)

    def lookup_by_tags(self, query: MetadataQuery) -> ProviderResult | None:
        return None

    def lookup_by_id(self, external_id: str, id_type: str) -> ProviderResult | None:
        return None

    def search(
        self,
        query: str,
        entity_type: Literal["artist", "album", "recording"],
        limit: int = 10,
    ) -> list[ProviderResult]:
        return []

    def _next_endpoint(self) -> AcoustIdProvider | None:
        with self._pick_lock:
            index = next(self._cycle)
        return self._endpoints[index]


def build_acoustid_endpoints(
    *,
    api_key: str = "",
    endpoints: tuple[Any, ...] = (),
) -> list[AcoustIdProvider]:
    """Build provider instances from config (legacy single key + endpoint list)."""
    built: list[AcoustIdProvider] = []
    for item in endpoints:
        key = ""
        proxy = ""
        label = ""
        if hasattr(item, "api_key"):
            key = str(getattr(item, "api_key", "") or "").strip()
            proxy = str(getattr(item, "proxy_url", "") or "").strip()
            label = str(getattr(item, "label", "") or "").strip()
        elif isinstance(item, dict):
            key = str(item.get("api_key") or "").strip()
            proxy = str(item.get("proxy_url") or "").strip()
            label = str(item.get("label") or "").strip()
        if not key:
            continue
        built.append(
            AcoustIdProvider(
                api_key=key,
                proxy_url=proxy or None,
                label=label or f"Account {len(built) + 1}",
            )
        )
    legacy = (api_key or "").strip()
    if not built and legacy:
        built.append(AcoustIdProvider(api_key=legacy, label="Primary"))
    return built
