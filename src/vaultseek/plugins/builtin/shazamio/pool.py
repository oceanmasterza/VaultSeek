"""Round-robin Shazamio pool — direct route + optional HTTP proxies.

Each route is rate-limited independently at ≤1 req/s (community-safe ceiling
for Shazam's unofficial API). With the main (direct) route plus up to three
proxies from Settings → AcoustID accounts, combined throughput approaches
~4 recognitions/sec without stacking load on a single public IP.
"""

from __future__ import annotations

import itertools
import threading
from typing import Any, Literal

from loguru import logger

from vaultseek.models.interfaces.metadata import MetadataQuery, ProviderResult
from vaultseek.plugins.builtin.shazamio.provider import ShazamioProvider


class ShazamioProviderPool:
    """Facade that rotates Shazamio routes (direct + proxies)."""

    provider_id = "shazamio"
    priority = 6
    plugin_id = "shazamio"

    def __init__(self, routes: list[ShazamioProvider]) -> None:
        if not routes:
            raise ValueError("ShazamioProviderPool requires at least one route")
        self._routes = routes
        self._cycle = itertools.cycle(range(len(routes)))
        self._pick_lock = threading.Lock()
        labels = [route.label for route in routes]
        logger.info(
            "Shazamio pool ready: {} route(s) — {}",
            len(routes),
            ", ".join(labels),
        )

    def recognize_file(self, file_path: str) -> ProviderResult | None:
        route = self._next_route()
        if route is None:
            return None
        return route.recognize_file(file_path)

    def lookup_by_fingerprint(self, fingerprint: bytes, duration: float) -> ProviderResult | None:
        return None

    def lookup_by_tags(self, query: MetadataQuery) -> ProviderResult | None:
        if query.file_path:
            return self.recognize_file(query.file_path)
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

    def _next_route(self) -> ShazamioProvider | None:
        with self._pick_lock:
            index = next(self._cycle)
        return self._routes[index]


def build_shazam_routes(*, endpoints: tuple[Any, ...] = ()) -> list[ShazamioProvider]:
    """Build rotated routes: always the direct path, then unique proxies.

    Proxy URLs are taken from AcoustID account rows so the same three
    Settings proxies also accelerate Shazam fallback — even when the
    AcoustID API key fields are empty.
    """
    routes: list[ShazamioProvider] = [
        ShazamioProvider(proxy_url=None, label="Direct"),
    ]
    seen_proxies: set[str] = set()
    for index, item in enumerate(endpoints, start=1):
        proxy = ""
        label = ""
        if hasattr(item, "proxy_url"):
            proxy = str(getattr(item, "proxy_url", "") or "").strip()
            label = str(getattr(item, "label", "") or "").strip()
        elif isinstance(item, dict):
            proxy = str(item.get("proxy_url") or "").strip()
            label = str(item.get("label") or "").strip()
        if not proxy or proxy in seen_proxies:
            continue
        seen_proxies.add(proxy)
        routes.append(
            ShazamioProvider(
                proxy_url=proxy,
                label=label or f"Proxy {index}",
            )
        )
    return routes
