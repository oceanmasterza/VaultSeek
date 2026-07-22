"""Discogs artwork provider — release primary image.

Priority 20 (after Cover Art Archive). Looks up by ``discogs_id`` when
known, otherwise searches artist + album. Requires a Discogs personal
access token.
"""

from __future__ import annotations

import threading
import time
from typing import Any
from urllib.parse import quote

import requests

from vaultseek.models.interfaces.artwork import ArtworkQuery, ArtworkResult
from vaultseek.plugins.imaging import image_dimensions

_API_ROOT = "https://api.discogs.com"
_USER_AGENT = "vaultseek/0.1.0 (https://github.com/oceanmasterza/vaultseek)"
_MIN_INTERVAL_SECONDS = 1.05


class DiscogsArtworkProvider:
    """Download primary cover images from Discogs releases."""

    provider_id = "discogs"
    priority = 20
    plugin_id = "discogs"

    def __init__(
        self,
        *,
        user_token: str | None = None,
        session: requests.Session | None = None,
        timeout_seconds: float = 15.0,
    ) -> None:
        self._token = (user_token or "").strip()
        self._session = session or requests.Session()
        self._session.headers.setdefault("User-Agent", _USER_AGENT)
        self._timeout = timeout_seconds
        self._rate_lock = threading.Lock()
        self._last_request_at = 0.0

    def fetch(self, query: ArtworkQuery) -> ArtworkResult | None:
        if not self._token:
            return None
        release_id = (query.discogs_id or "").strip()
        if not release_id and query.artist and query.album:
            release_id = self._search_release_id(query.artist, query.album) or ""
        if not release_id or not release_id.isdigit():
            return None
        return self._fetch_primary(release_id)

    def _search_release_id(self, artist: str, album: str) -> str | None:
        payload = self._get_json(
            f"{_API_ROOT}/database/search",
            {
                "type": "release",
                "artist": artist.strip(),
                "release_title": album.strip(),
                "per_page": 5,
                "page": 1,
            },
        )
        if payload is None:
            return None
        results = payload.get("results") or []
        if not results:
            return None
        best = results[0]
        rid = best.get("id")
        return str(rid) if rid is not None else None

    def _fetch_primary(self, release_id: str) -> ArtworkResult | None:
        payload = self._get_json(f"{_API_ROOT}/releases/{quote(release_id)}", {})
        if payload is None:
            return None
        image_url = _primary_image_url(payload)
        if not image_url:
            return None
        self._throttle()
        try:
            response = self._session.get(
                image_url,
                headers={"User-Agent": _USER_AGENT},
                timeout=self._timeout,
            )
            response.raise_for_status()
            data = response.content
        except requests.RequestException:
            return None
        if not data:
            return None
        mime = (response.headers.get("Content-Type") or "image/jpeg").split(";")[0].strip()
        dimensions = image_dimensions(data)
        if dimensions is None:
            return None
        width, height = dimensions
        return ArtworkResult(
            source="discogs",
            data=data,
            mime_type=mime or "image/jpeg",
            width=width,
            height=height,
            confidence=0.88,
            source_id=release_id,
        )

    def _get_json(self, url: str, params: dict[str, str | int]) -> dict[str, Any] | None:
        self._throttle()
        headers = {"Authorization": f"Discogs token={self._token}"}
        try:
            response = self._session.get(
                url, params=params, headers=headers, timeout=self._timeout
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError):
            return None
        return payload if isinstance(payload, dict) else None

    def _throttle(self) -> None:
        with self._rate_lock:
            now = time.monotonic()
            wait = _MIN_INTERVAL_SECONDS - (now - self._last_request_at)
            if wait > 0:
                time.sleep(wait)
            self._last_request_at = time.monotonic()


def _primary_image_url(release: dict[str, Any]) -> str | None:
    images = release.get("images") or []
    primary = None
    for image in images:
        uri = str(image.get("uri") or image.get("resource_url") or "").strip()
        if not uri:
            continue
        if str(image.get("type") or "").lower() == "primary":
            primary = uri
            break
        if primary is None:
            primary = uri
    return primary
