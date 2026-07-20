"""MusicBrainz metadata provider — recording lookup by MBID or tags."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import quote

import requests

from vaultseek.models.interfaces.metadata import (
    MetadataQuery,
    ProviderFieldResult,
    ProviderResult,
)

_MB_RECORDING_URL = "https://musicbrainz.org/ws/2/recording/"
_MB_RELEASE_URL = "https://musicbrainz.org/ws/2/release/"
_USER_AGENT = "VaultSeek/0.1.0 (https://github.com/oceanmasterza/VaultSeek)"
# MusicBrainz etiquette: ≤ 1 request/second for anonymous clients.
_MIN_INTERVAL_SECONDS = 1.05


@dataclass(frozen=True, slots=True)
class OfficialTrack:
    number: int
    title: str
    recording_mbid: str | None = None


@dataclass(frozen=True, slots=True)
class ReleaseTracklist:
    release_mbid: str
    title: str
    artist: str | None
    tracks: tuple[OfficialTrack, ...]

    @property
    def track_count(self) -> int:
        return len(self.tracks)


class MusicBrainzProvider:
    """Query the MusicBrainz Recording / Release APIs."""

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
        self._rate_lock = threading.Lock()
        self._last_request_at = 0.0

    def lookup_by_fingerprint(self, fingerprint: bytes, duration: float) -> ProviderResult | None:
        return None

    def lookup_by_tags(self, query: MetadataQuery) -> ProviderResult | None:
        parts = [p for p in (query.artist, query.title) if p]
        if len(parts) < 2:
            return None
        search = f'artist:"{query.artist}" AND recording:"{query.title}"'
        if query.album:
            search += f' AND release:"{query.album}"'
        params: dict[str, str | int] = {"query": search, "fmt": "json", "limit": 5}
        payload = self._get_json(_MB_RECORDING_URL, params)
        if payload is None:
            return None
        recordings = payload.get("recordings") or []
        if not recordings:
            return None
        best = max(recordings, key=lambda item: float(item.get("score") or 0.0))
        return _recording_to_result(best, lookup_method="tags", priority=self.priority)

    def lookup_by_id(self, external_id: str, id_type: str) -> ProviderResult | None:
        if id_type != "recording" or not external_id:
            return None
        params: dict[str, str] = {"fmt": "json", "inc": "artists+releases+release-groups"}
        payload = self._get_json(f"{_MB_RECORDING_URL}{quote(external_id)}", params)
        if payload is None:
            return None
        return _recording_to_result(payload, lookup_method="id", priority=self.priority)

    def lookup_release_tracklist(self, release_mbid: str) -> ReleaseTracklist | None:
        """Fetch the official track list for a release (folder sampling)."""
        if not release_mbid.strip():
            return None
        payload = self._get_json(
            f"{_MB_RELEASE_URL}{quote(release_mbid)}",
            {"fmt": "json", "inc": "recordings+artist-credits"},
        )
        if payload is None:
            return None
        tracks: list[OfficialTrack] = []
        for medium in payload.get("media") or []:
            for item in medium.get("tracks") or []:
                number = _parse_track_number(item.get("number") or item.get("position"))
                title = str(item.get("title") or "").strip()
                if number is None or not title:
                    continue
                recording = item.get("recording") or {}
                recording_id = recording.get("id")
                tracks.append(
                    OfficialTrack(
                        number=number,
                        title=title,
                        recording_mbid=str(recording_id) if recording_id else None,
                    )
                )
        if not tracks:
            return None
        credit = payload.get("artist-credit") or []
        artist: str | None = None
        if credit:
            artist = credit[0].get("name") or (credit[0].get("artist") or {}).get("name")
            if artist is not None:
                artist = str(artist)
        return ReleaseTracklist(
            release_mbid=release_mbid,
            title=str(payload.get("title") or "").strip() or release_mbid,
            artist=artist,
            tracks=tuple(tracks),
        )

    def search(
        self,
        query: str,
        entity_type: Literal["artist", "album", "recording"],
        limit: int = 10,
    ) -> list[ProviderResult]:
        if entity_type != "recording" or not query.strip():
            return []
        params: dict[str, str | int] = {"query": query, "fmt": "json", "limit": limit}
        payload = self._get_json(_MB_RECORDING_URL, params)
        if payload is None:
            return []
        results: list[ProviderResult] = []
        for recording in payload.get("recordings") or []:
            result = _recording_to_result(recording, lookup_method="search", priority=self.priority)
            if result is not None:
                results.append(result)
        return results

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


def _parse_track_number(value: object) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    digits = ""
    for char in text:
        if char.isdigit():
            digits += char
        elif digits:
            break
    return int(digits) if digits else None


def _recording_to_result(
    recording: dict[str, Any], *, lookup_method: str, priority: int
) -> ProviderResult | None:
    if lookup_method == "id":
        title_c, artist_c, album_c, year_c = 0.96, 0.95, 0.93, 0.88
    elif lookup_method == "tags":
        title_c, artist_c, album_c, year_c = 0.93, 0.92, 0.91, 0.85
    else:
        title_c, artist_c, album_c, year_c = 0.88, 0.88, 0.85, 0.80

    fields: list[ProviderFieldResult] = []
    mbid = recording.get("id")
    if mbid:
        fields.append(ProviderFieldResult("mb_recording_id", str(mbid), 0.97))
    title = recording.get("title")
    if title:
        fields.append(ProviderFieldResult("title", str(title), title_c))

    credit = recording.get("artist-credit") or []
    if credit:
        name = credit[0].get("name") or (credit[0].get("artist") or {}).get("name")
        if name:
            fields.append(ProviderFieldResult("artist", str(name), artist_c))

    releases = recording.get("releases") or []
    if releases:
        release = releases[0]
        album = release.get("title")
        if album:
            fields.append(ProviderFieldResult("album", str(album), album_c))
        date = release.get("date")
        if date and len(date) >= 4 and date[:4].isdigit():
            fields.append(ProviderFieldResult("year", int(date[:4]), year_c))
        release_id = release.get("id")
        if release_id:
            fields.append(ProviderFieldResult("mb_release_id", str(release_id), 0.95))
        release_group = release.get("release-group") or {}
        rg_id = release_group.get("id")
        if rg_id:
            fields.append(ProviderFieldResult("mb_release_group_id", str(rg_id), 0.93))

    if not any(f.field == "mb_release_group_id" for f in fields):
        groups = recording.get("release-groups") or []
        if groups and groups[0].get("id"):
            fields.append(
                ProviderFieldResult("mb_release_group_id", str(groups[0]["id"]), 0.90)
            )
            if not any(f.field == "album" for f in fields) and groups[0].get("title"):
                fields.append(
                    ProviderFieldResult("album", str(groups[0]["title"]), album_c)
                )

    if not fields:
        return None
    core_conf = [f.confidence for f in fields if f.field in _CORE]
    return ProviderResult(
        provider_id="musicbrainz",
        fields=fields,
        overall_confidence=min(core_conf) if core_conf else min(f.confidence for f in fields),
        lookup_method=lookup_method,
        raw_response=recording,
        priority=priority,
    )


_CORE = frozenset({"artist", "album", "title", "mb_recording_id"})
