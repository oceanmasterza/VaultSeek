"""Nicotine+ RPC client protocol — injectable until the wire format is fixed.

Nicotine+ does not expose a stable public search API yet. VaultSeek talks to
an installed client through this protocol so the provider can be tested with
a fake client and later swapped for a real TCP/JSON implementation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from vaultseek.models.interfaces.acquisition import SearchRequest, SearchResult


@dataclass(frozen=True, slots=True)
class RpcSearchHit:
    """Raw hit from a Nicotine+ RPC search response."""

    result_id: str
    display_name: str
    artist: str | None = None
    album: str | None = None
    title: str | None = None
    format: str | None = None
    bit_depth: int | None = None
    size_bytes: int | None = None
    track_count: int | None = None
    source_user: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RpcDownloadState:
    """Download progress from Nicotine+ RPC."""

    download_id: str
    state: str  # queued | downloading | completed | failed | cancelled
    progress: float = 0.0
    message: str = ""
    local_paths: tuple[Path, ...] = ()


class NicotinePlusRpcClient(Protocol):
    """Transport used by NicotinePlusProvider for search/download."""

    def search(self, request: SearchRequest) -> list[RpcSearchHit]: ...

    def enqueue_download(self, result_id: str, *, raw: dict[str, Any] | None = None) -> str: ...

    def download_status(self, download_id: str) -> RpcDownloadState: ...

    def cancel(self, download_id: str) -> bool: ...


class UnimplementedRpcClient:
    """Default client — connected probe succeeded but RPC methods are stubs."""

    def search(self, request: SearchRequest) -> list[RpcSearchHit]:
        return []

    def enqueue_download(self, result_id: str, *, raw: dict[str, Any] | None = None) -> str:
        return f"nicotine-{result_id}"

    def download_status(self, download_id: str) -> RpcDownloadState:
        return RpcDownloadState(
            download_id=download_id,
            state="failed",
            message="Nicotine+ RPC search/download not implemented yet.",
        )

    def cancel(self, download_id: str) -> bool:
        return True


class FakeRpcClient:
    """In-memory RPC client for unit tests."""

    def __init__(
        self,
        hits: list[RpcSearchHit] | None = None,
        *,
        complete_paths: list[Path] | None = None,
    ) -> None:
        self._hits = list(hits or [])
        self._complete_paths = list(complete_paths or [])
        self._downloads: dict[str, RpcDownloadState] = {}
        self.search_calls: list[SearchRequest] = []

    def search(self, request: SearchRequest) -> list[RpcSearchHit]:
        self.search_calls.append(request)
        return list(self._hits)

    def enqueue_download(self, result_id: str, *, raw: dict[str, Any] | None = None) -> str:
        download_id = f"fake-{result_id}"
        if self._complete_paths:
            self._downloads[download_id] = RpcDownloadState(
                download_id=download_id,
                state="completed",
                progress=1.0,
                local_paths=tuple(self._complete_paths),
            )
        else:
            self._downloads[download_id] = RpcDownloadState(
                download_id=download_id,
                state="downloading",
                progress=0.5,
            )
        return download_id

    def download_status(self, download_id: str) -> RpcDownloadState:
        return self._downloads.get(
            download_id,
            RpcDownloadState(download_id=download_id, state="failed", message="unknown"),
        )

    def cancel(self, download_id: str) -> bool:
        self._downloads[download_id] = RpcDownloadState(
            download_id=download_id,
            state="cancelled",
        )
        return True


def hits_to_search_results(hits: list[RpcSearchHit]) -> list[SearchResult]:
    return [
        SearchResult(
            provider_id="nicotine_plus",
            result_id=hit.result_id,
            display_name=hit.display_name,
            artist=hit.artist,
            album=hit.album,
            title=hit.title,
            format=hit.format,
            bit_depth=hit.bit_depth,
            size_bytes=hit.size_bytes,
            track_count=hit.track_count,
            source_user=hit.source_user,
            raw=dict(hit.raw),
        )
        for hit in hits
    ]
