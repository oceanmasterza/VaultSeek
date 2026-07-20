"""Acquisition provider protocol — discover and download missing music.

See docs/ARCHITECTURAL_UPDATE_001.md and ADR-0017. Providers talk only to
external systems. They never modify the library, import files, touch the UI,
or trigger media-server refreshes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    """What an acquisition provider can do."""

    search: bool = True
    browse: bool = False
    download: bool = True
    cancel: bool = True
    progress: bool = False


@dataclass(frozen=True, slots=True)
class SearchRequest:
    """Provider-independent search input produced by the Acquisition Engine."""

    artist: str | None = None
    album: str | None = None
    title: str | None = None
    year: int | None = None
    preferred_format: str | None = None
    track_count: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SearchResult:
    """One normalized hit from a provider (scoring is provider-neutral)."""

    provider_id: str
    result_id: str
    display_name: str
    artist: str | None = None
    album: str | None = None
    title: str | None = None
    year: int | None = None
    format: str | None = None
    bit_depth: int | None = None
    sample_rate: int | None = None
    size_bytes: int | None = None
    track_count: int | None = None
    source_user: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DownloadHandle:
    """Opaque handle for a queued or in-flight download."""

    provider_id: str
    download_id: str
    result_id: str


@dataclass(frozen=True, slots=True)
class DownloadStatus:
    """Progress snapshot for a download."""

    download_id: str
    state: str  # queued | downloading | completed | failed | cancelled
    progress: float = 0.0
    message: str = ""
    local_paths: tuple[Path, ...] = ()


@dataclass(frozen=True, slots=True)
class AcquisitionProviderConfig:
    """Connection / preference settings for one provider instance."""

    provider_id: str
    enabled: bool = True
    settings: dict[str, Any] = field(default_factory=dict)


class AcquisitionProvider(Protocol):
    """Pluggable source of search hits and downloaded files."""

    provider_id: str
    display_name: str

    @property
    def capabilities(self) -> ProviderCapabilities: ...

    def connect(self, config: AcquisitionProviderConfig) -> bool: ...

    def disconnect(self) -> None: ...

    def search(self, request: SearchRequest) -> list[SearchResult]: ...

    def download(self, result: SearchResult) -> DownloadHandle: ...

    def cancel(self, handle: DownloadHandle) -> bool: ...

    def get_status(self, handle: DownloadHandle) -> DownloadStatus: ...
