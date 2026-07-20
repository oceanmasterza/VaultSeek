"""Cover Art Archive artwork provider.

Fetches front-cover images from https://coverartarchive.org (priority 10
per docs/architecture/05-plugin-api.md, "Artwork Providers"). Lookup
order, from strongest to weakest handle:

1. Release MBID → ``/release/{mbid}/front`` (confidence 0.95)
2. Release-group MBID → ``/release-group/{mbid}/front`` (0.85)
3. Recording MBID → resolve a release id via the MusicBrainz recording
   API first, then fetch as in 1 (0.80)
4. Artist + album title → MusicBrainz release search, then CAA front
   (0.75). This path covers tag-first libraries that never received an
   MBID but still have clear artist/album tags — the common case when
   online artwork exists but local MBIDs do not.

The Archive answers ``/front`` with a redirect to the actual image;
`requests` follows it. A 404 means "no front cover" — that is a normal
miss, not an error.

MusicBrainz etiquette (≤ 1 request/second) is enforced for MB API
calls; CAA image fetches are not throttled beyond that. Recording and
artist+album → release lookups are cached in-process so album mates do
not repeat the same MusicBrainz search.
"""

from __future__ import annotations

import threading
import time
from typing import Any
from urllib.parse import quote

import requests

from vaultseek.models.interfaces.artwork import ArtworkQuery, ArtworkResult
from vaultseek.plugins.imaging import image_dimensions

_CAA_ROOT = "https://coverartarchive.org"
_MB_RECORDING_URL = "https://musicbrainz.org/ws/2/recording/"
_MB_RELEASE_URL = "https://musicbrainz.org/ws/2/release/"
_USER_AGENT = "VaultSeek/0.1.0 (https://github.com/oceanmasterza/VaultSeek)"
_MIN_INTERVAL_SECONDS = 1.05
_LOOKUP_CACHE_LIMIT = 512


class CoverArtArchiveProvider:
    """Download front covers from the Cover Art Archive."""

    provider_id = "cover_art_archive"
    priority = 10
    plugin_id = "cover_art_archive"

    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        timeout_seconds: float = 15.0,
    ) -> None:
        self._session = session or requests.Session()
        self._session.headers.setdefault("User-Agent", _USER_AGENT)
        self._timeout = timeout_seconds
        self._rate_lock = threading.Lock()
        self._last_request_at = 0.0
        self._cache_lock = threading.Lock()
        # Shared across threads: recording/search → release id (incl. misses).
        self._release_cache: dict[str, str | None] = {}

    def fetch(self, query: ArtworkQuery) -> ArtworkResult | None:
        if query.mb_release_id:
            result = self._fetch_front(
                f"{_CAA_ROOT}/release/{quote(query.mb_release_id)}/front",
                confidence=0.95,
                source_id=query.mb_release_id,
            )
            if result is not None:
                return result
        if query.mb_release_group_id:
            result = self._fetch_front(
                f"{_CAA_ROOT}/release-group/{quote(query.mb_release_group_id)}/front",
                confidence=0.85,
                source_id=query.mb_release_group_id,
            )
            if result is not None:
                return result
        if query.mb_recording_id:
            release_id = self._resolve_release_id(query.mb_recording_id)
            if release_id is not None:
                result = self._fetch_front(
                    f"{_CAA_ROOT}/release/{quote(release_id)}/front",
                    confidence=0.80,
                    source_id=release_id,
                )
                if result is not None:
                    return result
        if query.artist and query.album:
            release_id = self._search_release_id(query.artist, query.album)
            if release_id is not None:
                return self._fetch_front(
                    f"{_CAA_ROOT}/release/{quote(release_id)}/front",
                    confidence=0.75,
                    source_id=release_id,
                )
        return None

    def _fetch_front(self, url: str, *, confidence: float, source_id: str) -> ArtworkResult | None:
        try:
            response = self._session.get(url, timeout=self._timeout)
            response.raise_for_status()
        except requests.RequestException:
            return None
        data = response.content
        dimensions = image_dimensions(data)
        if not data or dimensions is None:
            return None
        width, height = dimensions
        mime = response.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()
        return ArtworkResult(
            source=self.provider_id,
            data=data,
            mime_type=mime or "image/jpeg",
            width=width,
            height=height,
            confidence=confidence,
            source_id=source_id,
        )

    def _resolve_release_id(self, recording_mbid: str) -> str | None:
        cache_key = f"rec:{recording_mbid}"
        with self._cache_lock:
            if cache_key in self._release_cache:
                return self._release_cache[cache_key]
        payload = self._get_json(
            f"{_MB_RECORDING_URL}{quote(recording_mbid)}",
            {"fmt": "json", "inc": "releases"},
        )
        release_id: str | None = None
        if payload is not None:
            releases = payload.get("releases") or []
            if releases:
                value = releases[0].get("id")
                release_id = str(value) if value else None
        self._cache_put(cache_key, release_id)
        return release_id

    def _search_release_id(self, artist: str, album: str) -> str | None:
        """Find a MusicBrainz release id from artist + album tags."""
        cache_key = f"search:{_normalize(artist)}|{_normalize(album)}"
        with self._cache_lock:
            if cache_key in self._release_cache:
                return self._release_cache[cache_key]
        query = f'artist:"{_escape_lucene(artist)}" AND release:"{_escape_lucene(album)}"'
        payload = self._get_json(
            _MB_RELEASE_URL,
            {"query": query, "fmt": "json", "limit": 5},
        )
        release_id: str | None = None
        if payload is not None:
            releases = payload.get("releases") or []
            if releases:
                wanted = _normalize(album)
                exact = [
                    release
                    for release in releases
                    if _normalize(str(release.get("title") or "")) == wanted
                ]
                pool = exact or releases
                best = max(pool, key=lambda item: float(item.get("score") or 0.0))
                value = best.get("id")
                release_id = str(value) if value else None
        self._cache_put(cache_key, release_id)
        return release_id

    def _cache_put(self, key: str, value: str | None) -> None:
        with self._cache_lock:
            if len(self._release_cache) >= _LOOKUP_CACHE_LIMIT and key not in self._release_cache:
                self._release_cache.pop(next(iter(self._release_cache)))
            self._release_cache[key] = value

    def _get_json(self, url: str, params: dict[str, str | int]) -> dict[str, Any] | None:
        self._throttle()
        try:
            response = self._session.get(url, params=params, timeout=self._timeout)
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


def _escape_lucene(value: str) -> str:
    """Escape Lucene special characters inside a quoted MB search term."""
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("(", "\\(")
        .replace(")", "\\)")
    )


def _normalize(value: str) -> str:
    return " ".join(value.casefold().split())
