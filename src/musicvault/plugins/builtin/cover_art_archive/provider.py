"""Cover Art Archive artwork provider.

Fetches front-cover images from https://coverartarchive.org (priority 10
per docs/architecture/05-plugin-api.md, "Artwork Providers"). Lookup
order, from strongest to weakest handle:

1. Release MBID → ``/release/{mbid}/front`` (confidence 0.95)
2. Release-group MBID → ``/release-group/{mbid}/front`` (0.85)
3. Recording MBID → resolve a release id via the MusicBrainz recording
   API first, then fetch as in 1 (0.80). This path matters because the
   pipeline persists ``tracks.mb_recording_id`` long before album rows
   (and their release MBIDs) exist.

The Archive answers ``/front`` with a redirect to the actual image;
`requests` follows it. A 404 means "no front cover" — that is a normal
miss, not an error.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import requests

from musicvault.models.interfaces.artwork import ArtworkQuery, ArtworkResult
from musicvault.plugins.imaging import image_dimensions

_CAA_ROOT = "https://coverartarchive.org"
_MB_RECORDING_URL = "https://musicbrainz.org/ws/2/recording/"
_USER_AGENT = "MusicVault/0.1.0 (https://github.com/oceanmasterza/MusicVault)"


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

    def fetch(self, query: ArtworkQuery) -> ArtworkResult | None:
        if query.mb_release_id:
            return self._fetch_front(
                f"{_CAA_ROOT}/release/{quote(query.mb_release_id)}/front",
                confidence=0.95,
                source_id=query.mb_release_id,
            )
        if query.mb_release_group_id:
            return self._fetch_front(
                f"{_CAA_ROOT}/release-group/{quote(query.mb_release_group_id)}/front",
                confidence=0.85,
                source_id=query.mb_release_group_id,
            )
        if query.mb_recording_id:
            release_id = self._resolve_release_id(query.mb_recording_id)
            if release_id is None:
                return None
            return self._fetch_front(
                f"{_CAA_ROOT}/release/{quote(release_id)}/front",
                confidence=0.80,
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
        params: dict[str, str] = {"fmt": "json", "inc": "releases"}
        try:
            response = self._session.get(
                f"{_MB_RECORDING_URL}{quote(recording_mbid)}",
                params=params,
                timeout=self._timeout,
            )
            response.raise_for_status()
            payload: dict[str, Any] = response.json()
        except requests.RequestException, ValueError:
            return None
        releases = payload.get("releases") or []
        if not releases:
            return None
        release_id = releases[0].get("id")
        return str(release_id) if release_id else None
