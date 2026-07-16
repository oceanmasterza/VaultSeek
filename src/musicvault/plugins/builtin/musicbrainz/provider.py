"""MusicBrainz metadata provider — recording lookup by MBID or tags."""

from __future__ import annotations

from typing import Any, Literal
from urllib.parse import quote

import requests

from musicvault.models.interfaces.metadata import (
    MetadataQuery,
    ProviderFieldResult,
    ProviderResult,
)

_MB_RECORDING_URL = "https://musicbrainz.org/ws/2/recording/"
_USER_AGENT = "MusicVault/0.1.0 (https://github.com/oceanmasterza/MusicVault)"


class MusicBrainzProvider:
    """Query the MusicBrainz Recording API."""

    provider_id = "musicbrainz"
    priority = 10
    plugin_id = "musicbrainz"

    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._session = session or requests.Session()
        self._session.headers.setdefault("User-Agent", _USER_AGENT)
        self._timeout = timeout_seconds

    def lookup_by_fingerprint(self, fingerprint: bytes, duration: float) -> ProviderResult | None:
        return None

    def lookup_by_tags(self, query: MetadataQuery) -> ProviderResult | None:
        parts = [p for p in (query.artist, query.title) if p]
        if len(parts) < 2:
            return None
        search = f'artist:"{query.artist}" AND recording:"{query.title}"'
        params: dict[str, str | int] = {"query": search, "fmt": "json", "limit": 1}
        try:
            response = self._session.get(
                _MB_RECORDING_URL,
                params=params,
                timeout=self._timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException, ValueError:
            return None
        recordings = payload.get("recordings") or []
        if not recordings:
            return None
        return _recording_to_result(recordings[0], lookup_method="tags", priority=self.priority)

    def lookup_by_id(self, external_id: str, id_type: str) -> ProviderResult | None:
        if id_type != "recording" or not external_id:
            return None
        params: dict[str, str] = {"fmt": "json", "inc": "artists+releases"}
        try:
            response = self._session.get(
                f"{_MB_RECORDING_URL}{quote(external_id)}",
                params=params,
                timeout=self._timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException, ValueError:
            return None
        return _recording_to_result(payload, lookup_method="id", priority=self.priority)

    def search(
        self,
        query: str,
        entity_type: Literal["artist", "album", "recording"],
        limit: int = 10,
    ) -> list[ProviderResult]:
        if entity_type != "recording" or not query.strip():
            return []
        params: dict[str, str | int] = {"query": query, "fmt": "json", "limit": limit}
        try:
            response = self._session.get(
                _MB_RECORDING_URL,
                params=params,
                timeout=self._timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException, ValueError:
            return []
        results: list[ProviderResult] = []
        for recording in payload.get("recordings") or []:
            result = _recording_to_result(recording, lookup_method="search", priority=self.priority)
            if result is not None:
                results.append(result)
        return results


def _recording_to_result(
    recording: dict[str, Any], *, lookup_method: str, priority: int
) -> ProviderResult | None:
    fields: list[ProviderFieldResult] = []
    mbid = recording.get("id")
    if mbid:
        fields.append(ProviderFieldResult("mb_recording_id", str(mbid), 0.95))
    title = recording.get("title")
    if title:
        fields.append(ProviderFieldResult("title", str(title), 0.92))

    credit = recording.get("artist-credit") or []
    if credit:
        name = credit[0].get("name") or (credit[0].get("artist") or {}).get("name")
        if name:
            fields.append(ProviderFieldResult("artist", str(name), 0.90))

    releases = recording.get("releases") or []
    if releases:
        album = releases[0].get("title")
        if album:
            fields.append(ProviderFieldResult("album", str(album), 0.85))
        date = releases[0].get("date")
        if date and len(date) >= 4 and date[:4].isdigit():
            fields.append(ProviderFieldResult("year", int(date[:4]), 0.80))

    if not fields:
        return None
    confidence = 0.95 if lookup_method == "id" else 0.80
    return ProviderResult(
        provider_id="musicbrainz",
        fields=fields,
        overall_confidence=min(confidence, min(f.confidence for f in fields)),
        lookup_method=lookup_method,
        raw_response=recording,
        priority=priority,
    )
