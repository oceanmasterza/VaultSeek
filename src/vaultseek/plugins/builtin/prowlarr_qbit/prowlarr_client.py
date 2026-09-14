"""Prowlarr search client (v1 JSON API).

Prowlarr aggregates many torrent/usenet indexers behind one API. VaultSeek
uses ``/api/v1/search`` and filters by protocol (torrent vs usenet) and
indexer privacy (public vs private) for the acquisition waterfall.
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
    indexer_id: int | None = None
    download_url: str = ""
    magnet_url: str = ""
    info_hash: str = ""
    size_bytes: int | None = None
    seeders: int | None = None
    categories: tuple[int, ...] = field(default_factory=tuple)
    protocol: str = ""  # torrent | usenet | …
    privacy: str = ""  # public | private | semiprivate | …

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

    @property
    def is_private(self) -> bool:
        privacy = self.privacy.casefold().replace("-", "").replace("_", "")
        return privacy in {"private", "semiprivate"}


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
        self._privacy_by_id: dict[int, str] | None = None
        self._privacy_by_name: dict[str, str] | None = None

    def configure(self, base_url: str, api_key: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._privacy_by_id = None
        self._privacy_by_name = None

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

    def refresh_indexer_privacy(self) -> None:
        """Load indexer id/name → privacy map used to classify search hits."""
        url = f"{self._base_url}/api/v1/indexer"
        try:
            response = self._session.get(url, headers=self._headers(), timeout=self._timeout)
        except requests.RequestException:
            self._privacy_by_id = {}
            self._privacy_by_name = {}
            return
        if response.status_code != 200:
            self._privacy_by_id = {}
            self._privacy_by_name = {}
            return
        try:
            payload = response.json()
        except ValueError:
            self._privacy_by_id = {}
            self._privacy_by_name = {}
            return
        by_id: dict[int, str] = {}
        by_name: dict[str, str] = {}
        rows = payload if isinstance(payload, list) else []
        for row in rows:
            if not isinstance(row, dict):
                continue
            privacy = str(row.get("privacy") or "").strip().casefold()
            name = str(row.get("name") or "").strip().casefold()
            raw_id = row.get("id")
            try:
                indexer_id = int(raw_id) if raw_id is not None else None
            except (TypeError, ValueError):
                indexer_id = None
            if indexer_id is not None and privacy:
                by_id[indexer_id] = privacy
            if name and privacy:
                by_name[name] = privacy
        self._privacy_by_id = by_id
        self._privacy_by_name = by_name

    def search(
        self,
        query: str,
        *,
        categories: tuple[int, ...] = (3000,),
        limit: int = 50,
        protocol: str | None = None,
        privacy: str | None = None,
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
        protocol_key = (protocol or "").casefold() or None
        privacy_key = (privacy or "").casefold() or None
        if privacy_key and self._privacy_by_id is None:
            self.refresh_indexer_privacy()
        results = [self._to_result(row) for row in rows if isinstance(row, dict)]
        if protocol_key or privacy_key:
            filtered: list[ProwlarrResult] = []
            for hit in results:
                if protocol_key == "usenet" and not hit.is_nzb:
                    continue
                if protocol_key == "torrent" and not hit.is_torrent:
                    continue
                if privacy_key == "public" and hit.is_private:
                    continue
                if privacy_key == "private" and not hit.is_private:
                    continue
                filtered.append(hit)
            return filtered
        return results

    def _to_result(self, row: dict[str, Any]) -> ProwlarrResult:
        categories: list[int] = []
        for category in row.get("categories") or []:
            if isinstance(category, dict) and category.get("id") is not None:
                try:
                    categories.append(int(category["id"]))
                except (TypeError, ValueError):
                    continue
        size = row.get("size")
        seeders = row.get("seeders")
        raw_indexer_id = row.get("indexerId")
        try:
            indexer_id = int(raw_indexer_id) if raw_indexer_id is not None else None
        except (TypeError, ValueError):
            indexer_id = None
        indexer_name = str(row.get("indexer") or "").strip()
        privacy = str(row.get("privacy") or "").strip().casefold()
        if not privacy:
            if indexer_id is not None and self._privacy_by_id:
                privacy = self._privacy_by_id.get(indexer_id, "")
            if not privacy and self._privacy_by_name:
                privacy = self._privacy_by_name.get(indexer_name.casefold(), "")
        return ProwlarrResult(
            title=str(row.get("title") or "").strip(),
            guid=str(row.get("guid") or row.get("downloadUrl") or ""),
            indexer=indexer_name,
            indexer_id=indexer_id,
            download_url=str(row.get("downloadUrl") or row.get("link") or ""),
            magnet_url=str(row.get("magnetUrl") or ""),
            info_hash=str(row.get("infoHash") or "").strip(),
            size_bytes=int(size) if isinstance(size, (int, float)) else None,
            seeders=int(seeders) if isinstance(seeders, (int, float)) else None,
            categories=tuple(categories),
            protocol=str(row.get("protocol") or "").strip().casefold(),
            privacy=privacy,
        )
