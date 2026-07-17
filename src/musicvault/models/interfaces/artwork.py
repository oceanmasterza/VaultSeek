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
    """Lookup input built from a Track and its Album (when known).

    ``mb_recording_id`` is included because the pipeline persists
    recording MBIDs long before album rows (and their release MBIDs)
    exist — providers that need a release id may resolve it from the
    recording.
    """

    file_path: str | None = None
    mb_release_id: str | None = None
    mb_release_group_id: str | None = None
    mb_recording_id: str | None = None
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
