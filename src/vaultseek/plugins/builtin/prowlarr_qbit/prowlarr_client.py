"""Prowlarr search client (v1 JSON API).

Prowlarr aggregates many torrent/usenet indexers behind one API. VaultSeek
uses its ``/api/v1/search`` endpoint and only cares about torrent results
(magnet or .torrent download URL) that qBittorrent can grab.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import requests


@dataclass(frozen=True, slots=True)
class ProwlarrResult:
    """One normalized indexer hit from Prowlarr."""

    title: str
    guid: str
    indexer: str = ""
    download_url: str = ""
    magnet_url: str = ""
    info_hash: str = ""
    size_bytes: int | None = None
    seeders: int | None = None
    categories: tuple[int, ...] = field(default_factory=tuple)
    protocol: str = ""  # torrent | usenet | …

    @property
    def is_torrent(self) -> bool:
        protocol = self.protocol.casefold()
        if protocol == "torrent":
            return True
        if protocol == "usenet":
            return False
        if self.magnet_url or self.info_hash:
            return True
        url = (self.download_url or "").casefold()
        return url.startswith("magnet:") or url.endswith(".torrent")

    @property
    def is_nzb(self) -> bool:
        protocol = self.protocol.casefold()
        if protocol == "usenet":
            return True
        if protocol == "torrent":
            return False
        url = (self.download_url or "").casefold()
        return ".nzb" in url or "nzb" in (self.indexer or "").casefold()

    @property
    def link(self) -> str:
        """Preferred hand-off URL — magnet first for torrents, else download URL."""
        if self.is_torrent:
            return self.magnet_url or self.download_url
        return self.download_url or self.magnet_url


class ProwlarrClient:
    """Minimal Prowlarr API client."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        session: requests.Session | None = None,
        timeout_seconds: float = 60.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._session = session or requests.Session()
        self._timeout = timeout_seconds

    def configure(self, base_url: str, api_key: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key

    def _headers(self) -> dict[str, str]:
        return {"X-Api-Key": self._api_key, "Accept": "application/json"}

    def probe(self) -> bool:
        """True when Prowlarr answers a system-status call with the API key."""
        url = f"{self._base_url}/api/v1/system/status"
        try:
            response = self._session.get(url, headers=self._headers(), timeout=self._timeout)
        except requests.RequestException:
            return False
        return response.status_code == 200

    def search(
        self,
        query: str,
        *,
        categories: tuple[int, ...] = (3000,),
        limit: int = 50,
    ) -> list[ProwlarrResult]:
        params: list[tuple[str, Any]] = [
            ("query", query),
            ("type", "search"),
            ("limit", limit),
        ]
        for category in categories:
            params.append(("categories", int(category)))
        url = f"{self._base_url}/api/v1/search"
        try:
            response = self._session.get(
                url, params=params, headers=self._headers(), timeout=self._timeout
            )
        except requests.RequestException as exc:
            raise ConnectionError(f"Prowlarr search failed: {exc}") from exc
        if response.status_code != 200:
            raise ConnectionError(f"Prowlarr search returned HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise ConnectionError("Prowlarr returned invalid JSON") from exc
        rows = payload if isinstance(payload, list) else []
        return [self._to_result(row) for row in rows if isinstance(row, dict)]

    @staticmethod
    def _to_result(row: dict[str, Any]) -> ProwlarrResult:
        categories: list[int] = []
        for category in row.get("categories") or []:
            if isinstance(category, dict) and category.get("id") is not None:
                try:
                    categories.append(int(category["id"]))
                except (TypeError, ValueError):
                    continue
        size = row.get("size")
        seeders = row.get("seeders")
        return ProwlarrResult(
            title=str(row.get("title") or "").strip(),
            guid=str(row.get("guid") or row.get("downloadUrl") or ""),
            indexer=str(row.get("indexer") or ""),
            download_url=str(row.get("downloadUrl") or row.get("link") or ""),
            magnet_url=str(row.get("magnetUrl") or ""),
            info_hash=str(row.get("infoHash") or "").strip(),
            size_bytes=int(size) if isinstance(size, (int, float)) else None,
            seeders=int(seeders) if isinstance(seeders, (int, float)) else None,
            categories=tuple(categories),
            protocol=str(row.get("protocol") or "").strip().casefold(),
        )
