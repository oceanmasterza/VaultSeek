"""Thin Last.fm Web API 2.0 client (read-only, JSON)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests

_API_ROOT = "https://ws.audioscrobbler.com/2.0/"
_USER_AGENT = "VaultSeek/1.0 (+https://github.com/oceanmasterza/VaultSeek)"


@dataclass(frozen=True, slots=True)
class SimilarArtist:
    name: str
    match: float


@dataclass(frozen=True, slots=True)
class TopAlbum:
    artist: str
    album: str


class LastfmClient:
    """Calls the ``artist.getSimilar`` and ``artist.getTopAlbums`` methods."""

    def __init__(
        self,
        api_key: str,
        *,
        session: requests.Session | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._api_key = api_key
        self._session = session or requests.Session()
        self._session.headers.setdefault("User-Agent", _USER_AGENT)
        self._timeout = timeout_seconds

    def _get(self, method: str, params: dict[str, Any]) -> dict[str, Any] | None:
        query = {
            "method": method,
            "api_key": self._api_key,
            "format": "json",
            **params,
        }
        try:
            response = self._session.get(_API_ROOT, params=query, timeout=self._timeout)
        except requests.RequestException as exc:
            raise ConnectionError(f"Last.fm request failed: {exc}") from exc
        if response.status_code != 200:
            raise ConnectionError(f"Last.fm returned HTTP {response.status_code} for {method}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise ConnectionError("Last.fm returned invalid JSON") from exc
        if isinstance(payload, dict) and payload.get("error"):
            raise ConnectionError(f"Last.fm error {payload.get('error')}: {payload.get('message')}")
        return payload if isinstance(payload, dict) else None

    def similar_artists(self, artist: str, *, limit: int = 5) -> list[SimilarArtist]:
        payload = self._get(
            "artist.getSimilar", {"artist": artist, "limit": max(1, limit), "autocorrect": 1}
        )
        if payload is None:
            return []
        block = payload.get("similarartists") or {}
        rows = block.get("artist") or []
        results: list[SimilarArtist] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            name = str(row.get("name") or "").strip()
            if not name:
                continue
            try:
                match = float(row.get("match") or 0.0)
            except (TypeError, ValueError):
                match = 0.0
            results.append(SimilarArtist(name=name, match=match))
        return results

    def top_albums(self, artist: str, *, limit: int = 2) -> list[TopAlbum]:
        payload = self._get(
            "artist.getTopAlbums", {"artist": artist, "limit": max(1, limit), "autocorrect": 1}
        )
        if payload is None:
            return []
        block = payload.get("topalbums") or {}
        rows = block.get("album") or []
        results: list[TopAlbum] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            album = str(row.get("name") or "").strip()
            artist_block = row.get("artist")
            artist_name = ""
            if isinstance(artist_block, dict):
                artist_name = str(artist_block.get("name") or "").strip()
            artist_name = artist_name or artist
            if not album or album.casefold() == "(null)":
                continue
            results.append(TopAlbum(artist=artist_name, album=album))
        return results
