"""Discogs metadata provider — release search by tags or release ID.

Complements MusicBrainz especially for electronic, vinyl reissues, and
label/catalog-heavy catalogs. Requires a Discogs personal access token
(Settings → Discogs token). Search needs auth; rate limit ≈ 60 req/min.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Literal
from urllib.parse import quote

import requests
from loguru import logger

from vaultseek.models.interfaces.metadata import (
    MetadataQuery,
    ProviderFieldResult,
    ProviderResult,
)

_API_ROOT = "https://api.discogs.com"
_USER_AGENT = "vaultseek/0.1.0 (https://github.com/oceanmasterza/vaultseek)"
# Authenticated Discogs: 60 requests/minute — stay under 1 req/sec.
_MIN_INTERVAL_SECONDS = 1.05
_WARNED_NO_TOKEN = False
_CORE = frozenset({"artist", "album", "title"})


class DiscogsProvider:
    """Query the Discogs Database API for release metadata."""

    provider_id = "discogs"
    priority = 20
    plugin_id = "discogs"

    def __init__(
        self,
        *,
        user_token: str | None = None,
        session: requests.Session | None = None,
        timeout_seconds: float = 12.0,
    ) -> None:
        self._token = (user_token or "").strip()
        self._session = session or requests.Session()
        self._session.headers.setdefault("User-Agent", _USER_AGENT)
        self._timeout = timeout_seconds
        self._rate_lock = threading.Lock()
        self._last_request_at = 0.0
        global _WARNED_NO_TOKEN
        if not self._token and not _WARNED_NO_TOKEN:
            _WARNED_NO_TOKEN = True
            logger.warning(
                "Discogs user token is empty — Discogs identification is disabled. "
                "Add a personal access token in Settings "
                "(https://www.discogs.com/settings/developers)."
            )

    def lookup_by_fingerprint(self, fingerprint: bytes, duration: float) -> ProviderResult | None:
        return None

    def lookup_by_tags(self, query: MetadataQuery) -> ProviderResult | None:
        if not self._token:
            return None
        artist = (query.artist or "").strip()
        album = (query.album or "").strip()
        title = (query.title or "").strip()
        # Discogs is release-centric: prefer artist + album; fall back to artist + title.
        if not artist or (not album and not title):
            return None

        params: dict[str, str | int] = {"type": "release", "per_page": 5, "page": 1}
        if album:
            params["artist"] = artist
            params["release_title"] = album
        else:
            params["q"] = f"{artist} {title}"
            params["artist"] = artist

        payload = self._get_json(f"{_API_ROOT}/database/search", params)
        if payload is None:
            return None
        results = payload.get("results") or []
        if not results:
            return None

        best = _pick_search_hit(results, artist=artist, album=album or title)
        release_id = best.get("id")
        if release_id is None:
            return None

        detail = self._get_json(f"{_API_ROOT}/releases/{int(release_id)}", {})
        if detail is None:
            # Search hit alone still carries useful fields.
            return _search_hit_to_result(
                best, lookup_method="tags", priority=self.priority, query_title=title
            )
        return _release_to_result(
            detail, lookup_method="tags", priority=self.priority, query_title=title
        )

    def lookup_by_id(self, external_id: str, id_type: str) -> ProviderResult | None:
        if not self._token or id_type not in {"release", "discogs"} or not external_id.strip():
            return None
        if not external_id.strip().isdigit():
            return None
        payload = self._get_json(f"{_API_ROOT}/releases/{quote(external_id.strip())}", {})
        if payload is None:
            return None
        return _release_to_result(payload, lookup_method="id", priority=self.priority)

    def search(
        self,
        query: str,
        entity_type: Literal["artist", "album", "recording"],
        limit: int = 10,
    ) -> list[ProviderResult]:
        if not self._token or not query.strip():
            return []
        type_map = {"artist": "artist", "album": "release", "recording": "release"}
        discogs_type = type_map.get(entity_type)
        if discogs_type is None:
            return []
        payload = self._get_json(
            f"{_API_ROOT}/database/search",
            {"q": query.strip(), "type": discogs_type, "per_page": limit, "page": 1},
        )
        if payload is None:
            return []
        out: list[ProviderResult] = []
        for hit in payload.get("results") or []:
            if discogs_type == "release":
                result = _search_hit_to_result(
                    hit, lookup_method="search", priority=self.priority
                )
            else:
                result = _artist_hit_to_result(hit, priority=self.priority)
            if result is not None:
                out.append(result)
        return out

    def list_artist_releases(
        self,
        artist_id: int | str,
        *,
        per_page: int = 100,
        max_pages: int = 5,
    ) -> list[dict[str, Any]]:
        """Return Discogs artist releases sorted by year (oldest first).

        Each item includes title, year, type, role, format, label, and related
        artist fields from the Discogs ``/artists/{id}/releases`` endpoint.
        """
        if not self._token:
            return []
        aid = str(artist_id).strip()
        if not aid.isdigit():
            return []
        releases: list[dict[str, Any]] = []
        page = 1
        while page <= max_pages:
            payload = self._get_json(
                f"{_API_ROOT}/artists/{quote(aid)}/releases",
                {
                    "sort": "year",
                    "sort_order": "asc",
                    "per_page": min(100, max(1, per_page)),
                    "page": page,
                },
            )
            if payload is None:
                break
            batch = payload.get("releases") or []
            if not isinstance(batch, list) or not batch:
                break
            for item in batch:
                if isinstance(item, dict):
                    releases.append(item)
            pagination = payload.get("pagination") or {}
            pages = int(pagination.get("pages") or page)
            if page >= pages:
                break
            page += 1
        releases.sort(key=lambda item: (_year_sort_key(item.get("year")), str(item.get("title") or "")))
        return releases

    def get_release_tracklist(
        self,
        release_id: int | str,
        *,
        kind: str = "release",
    ) -> list[dict[str, Any]]:
        """Return tracklist rows for a Discogs release or master."""
        if not self._token:
            return []
        rid = str(release_id).strip()
        if not rid.isdigit():
            return []
        path = "masters" if kind == "master" else "releases"
        payload = self._get_json(f"{_API_ROOT}/{path}/{quote(rid)}", {})
        if payload is None:
            return []
        # Masters often only list track titles; releases include duration/position.
        tracklist = payload.get("tracklist") or []
        if not isinstance(tracklist, list):
            return []
        rows: list[dict[str, Any]] = []
        for index, item in enumerate(tracklist, start=1):
            if not isinstance(item, dict):
                continue
            entry_type = str(item.get("type_") or item.get("type") or "track")
            if entry_type in {"heading", "index"}:
                continue
            title = str(item.get("title") or "").strip()
            if not title:
                continue
            position = str(item.get("position") or index).strip()
            duration = str(item.get("duration") or "").strip()
            artists = item.get("artists") or []
            extra_artists = item.get("extraartists") or []
            artist_bits: list[str] = []
            for group in (artists, extra_artists):
                if not isinstance(group, list):
                    continue
                for artist in group:
                    if not isinstance(artist, dict):
                        continue
                    name = _strip_artist_number(str(artist.get("name") or "").strip())
                    role = str(artist.get("role") or "").strip()
                    if name and role:
                        artist_bits.append(f"{name} ({role})")
                    elif name:
                        artist_bits.append(name)
            rows.append(
                {
                    "position": position,
                    "title": title,
                    "duration": duration,
                    "artists": "; ".join(artist_bits),
                }
            )
        return rows

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


def _year_sort_key(value: object) -> int:
    try:
        year = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 9999
    return year if year > 0 else 9999


def _pick_search_hit(
    results: list[dict[str, Any]], *, artist: str, album: str
) -> dict[str, Any]:
    """Prefer exact-ish title/artist matches; else first result."""
    artist_l = artist.casefold()
    album_l = album.casefold()

    def score(item: dict[str, Any]) -> tuple[int, int]:
        title = str(item.get("title") or "")
        title_l = title.casefold()
        exact_album = 1 if album_l and album_l in title_l else 0
        exact_artist = 1 if artist_l and artist_l in title_l else 0
        return (exact_album + exact_artist, -len(title))

    return max(results, key=score)


def _search_hit_to_result(
    hit: dict[str, Any],
    *,
    lookup_method: str,
    priority: int,
    query_title: str = "",
) -> ProviderResult | None:
    fields: list[ProviderFieldResult] = []
    release_id = hit.get("id")
    if release_id is not None:
        fields.append(ProviderFieldResult("discogs_id", str(release_id), 0.90))

    title_raw = str(hit.get("title") or "").strip()
    artist_name, album_title = _split_discogs_title(title_raw)
    if artist_name:
        fields.append(ProviderFieldResult("artist", artist_name, 0.82))
    if album_title:
        fields.append(ProviderFieldResult("album", album_title, 0.82))
    if query_title:
        fields.append(ProviderFieldResult("title", query_title, 0.55))

    year = hit.get("year")
    if year is not None and str(year).isdigit():
        fields.append(ProviderFieldResult("year", int(year), 0.78))

    genre = _join_styles(hit.get("genre"), hit.get("style"))
    if genre:
        fields.append(ProviderFieldResult("genre", genre, 0.75))

    if not fields:
        return None
    return _finish(fields, lookup_method=lookup_method, priority=priority, raw=hit)


def _artist_hit_to_result(hit: dict[str, Any], *, priority: int) -> ProviderResult | None:
    name = str(hit.get("title") or "").strip()
    if not name:
        return None
    fields = [ProviderFieldResult("artist", name, 0.80)]
    if hit.get("id") is not None:
        fields.append(ProviderFieldResult("discogs_artist_id", str(hit["id"]), 0.90))
    return _finish(fields, lookup_method="search", priority=priority, raw=hit)


def _release_to_result(
    release: dict[str, Any],
    *,
    lookup_method: str,
    priority: int,
    query_title: str = "",
) -> ProviderResult | None:
    if lookup_method == "id":
        artist_c, album_c, title_c, year_c, genre_c = 0.92, 0.92, 0.88, 0.88, 0.85
    else:
        artist_c, album_c, title_c, year_c, genre_c = 0.85, 0.85, 0.80, 0.80, 0.78

    fields: list[ProviderFieldResult] = []
    release_id = release.get("id")
    if release_id is not None:
        fields.append(ProviderFieldResult("discogs_id", str(release_id), 0.95))

    artists = release.get("artists") or []
    if artists:
        name = str(artists[0].get("name") or "").strip()
        if name:
            fields.append(ProviderFieldResult("artist", _strip_artist_number(name), artist_c))
        artist_id = artists[0].get("id")
        if artist_id is not None:
            fields.append(ProviderFieldResult("discogs_artist_id", str(artist_id), 0.93))

    album = str(release.get("title") or "").strip()
    if album:
        fields.append(ProviderFieldResult("album", album, album_c))

    year = release.get("year")
    if year is not None and str(year).isdigit() and int(year) > 0:
        fields.append(ProviderFieldResult("year", int(year), year_c))

    genre = _join_styles(release.get("genres"), release.get("styles"))
    if genre:
        fields.append(ProviderFieldResult("genre", genre, genre_c))

    labels = release.get("labels") or []
    if labels:
        label_name = str(labels[0].get("name") or "").strip()
        if label_name:
            fields.append(ProviderFieldResult("label", label_name, 0.80))
        catno = str(labels[0].get("catno") or "").strip()
        if catno and catno != "none":
            fields.append(ProviderFieldResult("catalog_number", catno, 0.82))

    country = str(release.get("country") or "").strip()
    if country:
        fields.append(ProviderFieldResult("country", country, 0.70))

    formats = release.get("formats") or []
    if formats:
        fmt_name = str(formats[0].get("name") or "").strip()
        if fmt_name:
            fields.append(ProviderFieldResult("format", fmt_name, 0.70))

    track_title, track_number = _match_tracklist(release.get("tracklist") or [], query_title)
    if track_title:
        fields.append(ProviderFieldResult("title", track_title, title_c))
    elif query_title:
        fields.append(ProviderFieldResult("title", query_title, 0.50))
    if track_number is not None:
        fields.append(ProviderFieldResult("track_number", track_number, 0.75))

    if not fields:
        return None
    return _finish(fields, lookup_method=lookup_method, priority=priority, raw=release)


def _match_tracklist(
    tracklist: list[dict[str, Any]], query_title: str
) -> tuple[str | None, int | None]:
    if not query_title.strip():
        return None, None
    needle = query_title.casefold().strip()
    for index, item in enumerate(tracklist, start=1):
        # Discogs uses type_ == "track" | "heading" | "index".
        entry_type = str(item.get("type_") or item.get("type") or "track")
        if entry_type in {"heading", "index"}:
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        title_l = title.casefold()
        if title_l == needle or needle in title_l or title_l in needle:
            position = _parse_position(item.get("position")) or index
            return title, position
    return None, None


def _parse_position(value: object) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    digits = ""
    for char in text:
        if char.isdigit():
            digits += char
        elif digits:
            break
    return int(digits) if digits else None


def _split_discogs_title(title: str) -> tuple[str | None, str | None]:
    """Search results use ``Artist - Release Title``."""
    if " - " in title:
        left, right = title.split(" - ", 1)
        return left.strip() or None, right.strip() or None
    return None, title or None


def _strip_artist_number(name: str) -> str:
    """Discogs disambiguates as ``Artist (2)`` — strip for library display."""
    if name.endswith(")") and " (" in name:
        base, _, suffix = name.rpartition(" (")
        if suffix[:-1].isdigit():
            return base.strip()
    return name


def _join_styles(genres: object, styles: object) -> str | None:
    parts: list[str] = []
    for group in (genres, styles):
        if isinstance(group, list):
            for item in group:
                text = str(item).strip()
                if text and text not in parts:
                    parts.append(text)
        elif isinstance(group, str) and group.strip():
            parts.append(group.strip())
    return "; ".join(parts) if parts else None


def _finish(
    fields: list[ProviderFieldResult],
    *,
    lookup_method: str,
    priority: int,
    raw: dict[str, Any],
) -> ProviderResult:
    core = [f.confidence for f in fields if f.field in _CORE]
    return ProviderResult(
        provider_id="discogs",
        fields=fields,
        overall_confidence=min(core) if core else min(f.confidence for f in fields),
        lookup_method=lookup_method,
        raw_response=raw,
        priority=priority,
    )
