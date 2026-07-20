"""AcoustID HTTP metadata provider — fingerprint → MusicBrainz recording ID."""

from __future__ import annotations

import threading
import time
from typing import Any, Literal

import requests
from loguru import logger

from vaultseek.models.interfaces.metadata import (
    MetadataQuery,
    ProviderFieldResult,
    ProviderResult,
)

_ACOUSTID_LOOKUP_URL = "https://api.acoustid.org/v2/lookup"
# AcoustID free tier: do not exceed 3 requests/second (same guideline as Picard).
_MIN_INTERVAL_SECONDS = 1.0 / 3.0
_WARNED_NO_KEY = False


class AcoustIdProvider:
    """Look up a Chromaprint against the AcoustID web service."""

    provider_id = "acoustid"
    priority = 5
    plugin_id = "acoustid"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        session: requests.Session | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._api_key = (api_key or "").strip()
        self._session = session or requests.Session()
        self._timeout = timeout_seconds
        self._rate_lock = threading.Lock()
        self._last_request_at = 0.0
        global _WARNED_NO_KEY
        if not self._api_key and not _WARNED_NO_KEY:
            _WARNED_NO_KEY = True
            logger.warning(
                "AcoustID API key is empty — fingerprint identification is disabled. "
                "Add a free application key in Settings (https://acoustid.org/new-applications)."
            )

    def lookup_by_fingerprint(self, fingerprint: bytes, duration: float) -> ProviderResult | None:
        if not self._api_key:
            return None
        fingerprint_text = (
            fingerprint.decode("utf-8") if isinstance(fingerprint, bytes) else str(fingerprint)
        )
        params: dict[str, str | int] = {
            "client": self._api_key,
            "meta": "recordings+releasegroups+releases+compress",
            "duration": max(1, int(round(duration))),
            "fingerprint": fingerprint_text,
        }
        self._throttle()
        try:
            response = self._session.get(
                _ACOUSTID_LOOKUP_URL,
                params=params,
                timeout=self._timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError):
            return None

        return _parse_acoustid_response(payload, priority=self.priority)

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

    def _throttle(self) -> None:
        with self._rate_lock:
            now = time.monotonic()
            wait = _MIN_INTERVAL_SECONDS - (now - self._last_request_at)
            if wait > 0:
                time.sleep(wait)
            self._last_request_at = time.monotonic()


def _parse_acoustid_response(payload: dict[str, Any], *, priority: int) -> ProviderResult | None:
    if payload.get("status") != "ok":
        return None
    results = payload.get("results") or []
    if not results:
        return None
    best = max(results, key=lambda item: float(item.get("score") or 0.0))
    score = float(best.get("score") or 0.0)
    # Weak fingerprint matches should not auto-approve.
    if score < 0.5:
        return None

    acoustid = best.get("id")
    recordings = best.get("recordings") or []
    mbid = None
    title = None
    artist = None
    album = None
    release_id = None
    release_group_id = None
    if recordings:
        recording = recordings[0]
        mbid = recording.get("id")
        title = recording.get("title")
        artists = recording.get("artists") or []
        if artists:
            artist = artists[0].get("name")
        releasegroups = recording.get("releasegroups") or []
        if releasegroups:
            album = releasegroups[0].get("title")
            release_group_id = releasegroups[0].get("id")
        releases = recording.get("releases") or []
        if releases:
            release_id = releases[0].get("id")
            if not album:
                album = releases[0].get("title")

    # High AcoustID scores clear the default 0.90 auto-approve gate.
    identity_confidence = min(0.98, max(0.90, score))

    fields: list[ProviderFieldResult] = []
    if acoustid:
        fields.append(ProviderFieldResult("acoustid_id", str(acoustid), score))
    fields.append(ProviderFieldResult("acoustid_score", score, score))
    if mbid:
        fields.append(ProviderFieldResult("mb_recording_id", str(mbid), identity_confidence))
    if title:
        fields.append(ProviderFieldResult("title", str(title), identity_confidence))
    if artist:
        fields.append(ProviderFieldResult("artist", str(artist), identity_confidence))
    if album:
        fields.append(ProviderFieldResult("album", str(album), identity_confidence))
    if release_id:
        fields.append(ProviderFieldResult("mb_release_id", str(release_id), identity_confidence))
    if release_group_id:
        fields.append(
            ProviderFieldResult("mb_release_group_id", str(release_group_id), identity_confidence)
        )
    if not fields:
        return None
    return ProviderResult(
        provider_id="acoustid",
        fields=fields,
        overall_confidence=min(f.confidence for f in fields),
        lookup_method="fingerprint",
        raw_response=payload,
        priority=priority,
    )
