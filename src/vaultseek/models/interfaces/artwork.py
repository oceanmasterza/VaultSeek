"""Artwork provider protocol — pluggable album-art sources.

See docs/architecture/05-plugin-api.md ("Artwork Providers"): Cover Art
Archive (priority 10) > Discogs (20, future) > Embedded (50). The
:class:`ArtworkResult` dataclass matches the documented shape exactly;
:class:`ArtworkQuery` is this implementation's fill-in (the document
never specified the provider's input) mirroring `MetadataQuery`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ArtworkQuery:
    """Album-scoped cover lookup input.

    Providers must search by release / release-group / Discogs id or
    artist+album title only. ``mb_recording_id`` is retained for API
    compatibility but is ignored — song/recording identity is never used
    to fetch artwork (the worker defers until an album is known).
    """

    file_path: str | None = None
    mb_release_id: str | None = None
    mb_release_group_id: str | None = None
    mb_recording_id: str | None = None
    discogs_id: str | None = None
    artist: str | None = None
    album: str | None = None


@dataclass(frozen=True, slots=True)
class ArtworkResult:
    """One candidate image returned by a provider."""

    source: str
    data: bytes
    mime_type: str
    width: int
    height: int
    confidence: float
    source_id: str | None = None


class ArtworkProvider(Protocol):
    """A pluggable source of album artwork."""

    provider_id: str
    priority: int

    def fetch(self, query: ArtworkQuery) -> ArtworkResult | None: ...
