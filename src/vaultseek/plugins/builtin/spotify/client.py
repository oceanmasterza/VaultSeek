"""Spotify Web API client using the Client Credentials flow.

Client Credentials needs no user login and can read *public* playlists,
which is all the playlist-sync recommender requires. Private/collaborative
playlists would need the Authorization Code flow and a redirect dance —
out of scope for a background recommender.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import requests

_TOKEN_URL = "https://accounts.spotify.com/api/token"
_API_ROOT = "https://api.spotify.com/v1"


@dataclass(frozen=True, slots=True)
class PlaylistTrack:
    artist: str
    album: str
    title: str
    year: int | None = None


def parse_playlist_id(value: str) -> str | None:
    """Extract a playlist id from a share URL, URI, or bare id."""
    text = (value or "").strip()
    if not text:
        return None
    # spotify:playlist:37i9dQ...
    if text.startswith("spotify:playlist:"):
        return text.split(":", 2)[2].split("?")[0] or None
    # https://open.spotify.com/playlist/37i9dQ...?si=...
    if "open.spotify.com" in text and "playlist" in text:
        after = text.split("playlist/", 1)[1] if "playlist/" in text else ""
        candidate = after.split("?")[0].split("/")[0]
        return candidate or None
    # Bare id (alphanumeric base62).
    if text.replace("_", "").replace("-", "").isalnum():
        return text
    return None


class SpotifyClient:
    """Fetches public playlist tracks after obtaining an app access token."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        *,
        session: requests.Session | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._session = session or requests.Session()
        self._timeout = timeout_seconds
        self._token: str | None = None
        self._token_expiry: float = 0.0

    def _access_token(self) -> str:
        now = time.monotonic()
        if self._token and now < self._token_expiry:
            return self._token
        try:
            response = self._session.post(
                _TOKEN_URL,
                data={"grant_type": "client_credentials"},
                auth=(self._client_id, self._client_secret),
                timeout=self._timeout,
            )
        except requests.RequestException as exc:
            raise ConnectionError(f"Spotify token request failed: {exc}") from exc
        if response.status_code != 200:
            raise ConnectionError(
                f"Spotify token request returned HTTP {response.status_code}. "
                "Check the client id/secret."
            )
        payload = response.json()
        token = str(payload.get("access_token") or "")
        if not token:
            raise ConnectionError("Spotify token response missing access_token")
        expires_in = float(payload.get("expires_in") or 3600)
        self._token = token
        self._token_expiry = now + max(30.0, expires_in - 60.0)
        return token

    def _get(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        token = self._access_token()
        try:
            response = self._session.get(
                url,
                params=params,
                headers={"Authorization": f"Bearer {token}"},
                timeout=self._timeout,
            )
        except requests.RequestException as exc:
            raise ConnectionError(f"Spotify request failed: {exc}") from exc
        if response.status_code != 200:
            raise ConnectionError(f"Spotify returned HTTP {response.status_code}")
        payload = response.json()
        return payload if isinstance(payload, dict) else {}

    def playlist_tracks(self, playlist_id: str) -> list[PlaylistTrack]:
        """All tracks in a public playlist, following pagination."""
        tracks: list[PlaylistTrack] = []
        url: str | None = f"{_API_ROOT}/playlists/{playlist_id}/tracks"
        params: dict[str, Any] | None = {
            "limit": 100,
            "fields": "next,items(track(name,album(name,release_date),artists(name)))",
        }
        while url:
            payload = self._get(url, params)
            for item in payload.get("items") or []:
                track = (item or {}).get("track") or {}
                name = str(track.get("name") or "").strip()
                artists = track.get("artists") or []
                artist = ""
                if artists and isinstance(artists[0], dict):
                    artist = str(artists[0].get("name") or "").strip()
                album_block = track.get("album") or {}
                album = str(album_block.get("name") or "").strip()
                year = _year_from_release_date(album_block.get("release_date"))
                if not artist or not album:
                    continue
                tracks.append(PlaylistTrack(artist=artist, album=album, title=name, year=year))
            url = payload.get("next")
            params = None  # `next` is a fully-formed URL.
        return tracks


def _year_from_release_date(value: Any) -> int | None:
    text = str(value or "").strip()
    if len(text) >= 4 and text[:4].isdigit():
        return int(text[:4])
    return None
