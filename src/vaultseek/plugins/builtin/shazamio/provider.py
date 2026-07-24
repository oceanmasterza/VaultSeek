"""Shazamio HTTP metadata provider — audio file → title/artist/album.

Used as a fingerprint-identity fallback when AcoustID has no API key or
returns no match. Each instance is bound to one network route (direct or a
single HTTP proxy) and is rate-limited independently.

Community guidance (shazamio issues #81 / #120): Shazam rate-limits by
public IP and returns HTTP 429 under burst load. Stay at ≤1 request/second
per IP — comfortably under the informal ~2/s ceiling discussed by users —
and fan out across the direct route plus configured proxies for throughput.

The rate lock is held for the **entire** recognize (not just the sleep) so
multiple metadata-worker threads cannot overlap on the same public IP.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Literal

from loguru import logger

from vaultseek.models.interfaces.metadata import (
    MetadataQuery,
    ProviderFieldResult,
    ProviderResult,
)
from vaultseek.plugins.builtin.shazamio.backend import recognize_with_shazamio

# ≤1 req/s per public IP — conservative vs community "~2/s before 429" reports.
_MIN_INTERVAL_SECONDS = 1.0


class ShazamioProvider:
    """Recognize a local audio file via Shazamio on one network route."""

    provider_id = "shazamio"
    priority = 6  # Just below AcoustID (5) so AcoustID wins when both hit.
    plugin_id = "shazamio"

    def __init__(
        self,
        *,
        proxy_url: str | None = None,
        label: str = "",
    ) -> None:
        self._proxy_url = (proxy_url or "").strip() or None
        self._label = (label or "").strip() or (
            f"Proxy {self._proxy_url}" if self._proxy_url else "Direct"
        )
        # Serializes throttle + network for this route (thread-safe under N workers).
        self._rate_lock = threading.Lock()
        self._last_request_at = 0.0

    @property
    def label(self) -> str:
        return self._label

    @property
    def proxy_url(self) -> str | None:
        return self._proxy_url

    def recognize_file(self, file_path: str) -> ProviderResult | None:
        """Identify ``file_path`` through Shazam on this route."""
        path = (file_path or "").strip()
        if not path:
            return None
        with self._rate_lock:
            now = time.monotonic()
            wait = _MIN_INTERVAL_SECONDS - (now - self._last_request_at)
            if wait > 0:
                time.sleep(wait)
            try:
                payload = recognize_with_shazamio(path, proxy_url=self._proxy_url)
            finally:
                # Stamp after the call so overlapping workers cannot burst.
                self._last_request_at = time.monotonic()
        if not payload:
            return None
        return _parse_shazam_response(payload, priority=self.priority)

    def lookup_by_fingerprint(self, fingerprint: bytes, duration: float) -> ProviderResult | None:
        # Shazam needs the audio file, not a Chromaprint — see recognize_file.
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


def _parse_shazam_response(payload: dict[str, Any], *, priority: int) -> ProviderResult | None:
    """Map a Shazamio ``recognize`` payload into VaultSeek provider fields."""
    track = payload.get("track")
    if not isinstance(track, dict) or not track:
        # No match — empty matches list is normal when Shazam doesn't know the clip.
        return None

    title = _as_nonempty_str(track.get("title"))
    artist = _as_nonempty_str(track.get("subtitle"))
    album = _extract_album(track)
    shazam_key = _as_nonempty_str(track.get("key"))
    isrc = _extract_isrc(track)

    # A concrete track object is a strong hit; keep confidence high enough to
    # clear the default 0.90 auto-approve gate when core fields are present.
    identity_confidence = 0.93

    fields: list[ProviderFieldResult] = []
    if shazam_key:
        fields.append(ProviderFieldResult("shazam_track_id", shazam_key, identity_confidence))
    if title:
        fields.append(ProviderFieldResult("title", title, identity_confidence))
    if artist:
        fields.append(ProviderFieldResult("artist", artist, identity_confidence))
    if album:
        fields.append(ProviderFieldResult("album", album, identity_confidence))
    if isrc:
        fields.append(ProviderFieldResult("isrc", isrc, identity_confidence))

    if not fields:
        return None

    logger.debug(
        "Shazamio match: {} — {} ({})",
        artist or "?",
        title or "?",
        album or "no album",
    )
    return ProviderResult(
        provider_id="shazamio",
        fields=fields,
        overall_confidence=min(field.confidence for field in fields),
        lookup_method="audio",
        raw_response=payload,
        priority=priority,
    )


def _extract_album(track: dict[str, Any]) -> str | None:
    for section in track.get("sections") or []:
        if not isinstance(section, dict):
            continue
        if section.get("type") != "SONG":
            continue
        for meta in section.get("metadata") or []:
            if not isinstance(meta, dict):
                continue
            if str(meta.get("title") or "").strip().lower() == "album":
                return _as_nonempty_str(meta.get("text"))
    return None


def _extract_isrc(track: dict[str, Any]) -> str | None:
    for section in track.get("sections") or []:
        if not isinstance(section, dict):
            continue
        for meta in section.get("metadata") or []:
            if not isinstance(meta, dict):
                continue
            if str(meta.get("title") or "").strip().upper() == "ISRC":
                return _as_nonempty_str(meta.get("text"))
    return None


def _as_nonempty_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
