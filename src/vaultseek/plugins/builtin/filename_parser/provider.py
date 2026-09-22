"""Filename parser metadata provider — extract tags from path/name."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from vaultseek.models.interfaces.metadata import (
    MetadataQuery,
    ProviderFieldResult,
    ProviderResult,
)
from vaultseek.services.review_display import looks_like_opaque_id

# Common patterns: "Artist - Album/01. Title.ext" and "Artist - Title.ext"
_TRACK_IN_ALBUM = re.compile(
    r"^(?P<artist>.+?)\s+-\s+(?P<album>.+?)[/\\](?P<track>\d+)\.\s*(?P<title>.+?)$",
    re.IGNORECASE,
)
_ARTIST_TITLE = re.compile(
    r"^(?P<artist>.+?)\s+-\s+(?P<title>.+?)$",
    re.IGNORECASE,
)
# "10 - Soul Messiah" / "10. Title" / "10_Title" (Soulseek / scene folders)
_TRACK_NUM_TITLE = re.compile(
    r"^(?P<track>\d{1,3})\s*[-._)]\s*(?P<title>.+?)$",
    re.IGNORECASE,
)
# Strip trailing release noise only — never mid-UUID segments like -7dbc-7000.
_SCENE_NOISE = re.compile(
    r"(?:[\s._-]+(?:\(\d{4}\)|\[[\w.-]+\]|WEB|FLAC|MP3|320|256|192))+$",
    re.IGNORECASE,
)


class FilenameParserProvider:
    """Parse artist/album/title from the file path when tags are missing."""

    provider_id = "filename_parser"
    priority = 90
    plugin_id = "filename_parser"

    def lookup_by_fingerprint(self, fingerprint: bytes, duration: float) -> ProviderResult | None:
        return None

    def lookup_by_tags(self, query: MetadataQuery) -> ProviderResult | None:
        stem_path = query.file_path or query.file_name
        if not stem_path:
            return None
        path = Path(stem_path)
        fields: list[ProviderFieldResult] = []
        # Prefer "artist - album/01. title" when the parent is a real folder name.
        # Nicotine+ download folders are often UUIDs — skip those so the stem wins.
        parent_name = path.parent.name
        if parent_name and parent_name not in (".",) and not looks_like_opaque_id(parent_name):
            fields = _parse(f"{parent_name}/{path.stem}")
        if not fields:
            fields = _parse(path.stem)
        if not fields:
            return None
        confidences = [f.confidence for f in fields]
        return ProviderResult(
            provider_id=self.provider_id,
            fields=fields,
            overall_confidence=min(confidences),
            lookup_method="filename",
            priority=self.priority,
        )

    def lookup_by_id(self, external_id: str, id_type: str) -> ProviderResult | None:
        return None

    def search(
        self,
        query: str,
        entity_type: Literal["artist", "album", "recording"],
        limit: int = 10,
    ) -> list[ProviderResult]:
        return []


def _parse(text: str) -> list[ProviderFieldResult]:
    cleaned = _SCENE_NOISE.sub("", text).strip(" .-_")
    if not cleaned or looks_like_opaque_id(cleaned):
        return []
    match = _TRACK_IN_ALBUM.match(cleaned.replace("\\", "/"))
    if match is not None:
        title = match.group("title").strip()
        if looks_like_opaque_id(title):
            return []
        return [
            ProviderFieldResult("artist", match.group("artist").strip(), 0.55),
            ProviderFieldResult("album", match.group("album").strip(), 0.50),
            ProviderFieldResult("title", title, 0.55),
            ProviderFieldResult("track_number", int(match.group("track")), 0.60),
        ]
    # "10 - Soul Messiah" before treating "Artist - Title" (numeric left side).
    match = _TRACK_NUM_TITLE.match(cleaned)
    if match is not None:
        title = _SCENE_NOISE.sub("", match.group("title")).strip(" .-_")
        if title and not looks_like_opaque_id(title):
            return [
                ProviderFieldResult("title", title, 0.50),
                ProviderFieldResult("track_number", int(match.group("track")), 0.55),
            ]
    match = _ARTIST_TITLE.match(cleaned)
    if match is not None:
        artist = match.group("artist").strip()
        title = match.group("title").strip()
        # Avoid "01a090ad-7dbc-…/10 - Title" leftovers and track-num false artists.
        if artist.isdigit() or looks_like_opaque_id(artist) or looks_like_opaque_id(title):
            return []
        return [
            ProviderFieldResult("artist", artist, 0.45),
            ProviderFieldResult("title", title, 0.45),
        ]
    if cleaned and not looks_like_opaque_id(cleaned):
        return [ProviderFieldResult("title", cleaned, 0.30)]
    return []
