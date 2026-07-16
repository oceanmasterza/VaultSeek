"""AcoustID HTTP metadata provider — fingerprint → MusicBrainz recording ID."""

from __future__ import annotations

from typing import Any, Literal

import requests

from musicvault.models.interfaces.metadata import (
    MetadataQuery,
    ProviderFieldResult,
    ProviderResult,
)

_ACOUSTID_LOOKUP_URL = "https://api.acoustid.org/v2/lookup"


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
        self._api_key = api_key or ""
        self._session = session or requests.Session()
        self._timeout = timeout_seconds

    def lookup_by_fingerprint(self, fingerprint: bytes, duration: float) -> ProviderResult | None:
        if not self._api_key:
            return None
        fingerprint_text = (
            fingerprint.decode("utf-8") if isinstance(fingerprint, bytes) else str(fingerprint)
        )
        params: dict[str, str | int] = {
            "client": self._api_key,
            "meta": "recordings",
            "duration": int(duration),
            "fingerprint": fingerprint_text,
        }
        try:
            response = self._session.get(
                _ACOUSTID_LOOKUP_URL,
                params=params,
                timeout=self._timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException, ValueError:
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


def _parse_acoustid_response(payload: dict[str, Any], *, priority: int) -> ProviderResult | None:
    if payload.get("status") != "ok":
        return None
    results = payload.get("results") or []
    if not results:
        return None
    best = max(results, key=lambda item: float(item.get("score") or 0.0))
    score = float(best.get("score") or 0.0)
    acoustid = best.get("id")
    recordings = best.get("recordings") or []
    mbid = None
    title = None
    artist = None
    if recordings:
        recording = recordings[0]
        mbid = recording.get("id")
        title = recording.get("title")
        artists = recording.get("artists") or []
        if artists:
            artist = artists[0].get("name")

    fields: list[ProviderFieldResult] = []
    if acoustid:
        fields.append(ProviderFieldResult("acoustid_id", str(acoustid), score))
    fields.append(ProviderFieldResult("acoustid_score", score, score))
    if mbid:
        fields.append(ProviderFieldResult("mb_recording_id", str(mbid), min(0.99, score + 0.05)))
    if title:
        fields.append(ProviderFieldResult("title", str(title), min(0.95, score)))
    if artist:
        fields.append(ProviderFieldResult("artist", str(artist), min(0.90, score)))
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
