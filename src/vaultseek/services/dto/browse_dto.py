"""Browse DTOs for Artists / Albums / Artwork / Library folder views."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ArtistBrowseRow:
    artist_id: UUID
    name: str
    sort_name: str
    track_count: int
    album_count: int
    mbid: str | None = None


@dataclass(frozen=True, slots=True)
class AlbumBrowseRow:
    album_id: UUID
    title: str
    sort_title: str
    artist_name: str | None
    artist_id: UUID | None
    year: int | None
    track_count: int
    has_cover: bool
    mbid: str | None = None


@dataclass(frozen=True, slots=True)
class ArtworkBrowseRow:
    """One album (preferred) or orphan track needing/having cover art."""

    album_id: UUID | None
    track_id: UUID | None
    label: str
    artist_name: str | None
    track_count: int
    has_cover: bool
    cover_source: str | None
    width: int | None
    height: int | None
    status: str  # "ok" | "missing" | "low_res"


@dataclass(frozen=True, slots=True)
class TrackPathRow:
    track_id: UUID
    zone: str
    file_path: str
    file_name: str
    title: str | None
    artist_id: UUID | None
    album_id: UUID | None
