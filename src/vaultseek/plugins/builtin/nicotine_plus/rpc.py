"""Nicotine+ RPC client protocol and transports.

Nicotine+ does **not** ship a stable public search/download API. External
control requires a plugin (e.g. community ``api-nicotine-plus`` HTTP on
port 12339). VaultSeek therefore defines its own line-delimited JSON
socket protocol so a companion Nicotine+ plugin (or shim) can speak a
documented wire format.

Transports:

* :class:`FakeRpcClient` — in-memory, for unit tests
* :class:`LocalSocketRpcClient` — TCP + NDJSON; fails gracefully when nothing
  is listening or the peer does not speak the protocol
* :class:`UnimplementedRpcClient` — empty stubs (legacy default)

Wire protocol (one UTF-8 JSON object per line, ``\\n`` terminated)::

    → {"id":"…","method":"search","params":{"query":"…","artist":null,…}}
    ← {"id":"…","ok":true,"result":{"hits":[{…},…]}}

    → {"id":"…","method":"enqueue_download","params":{"result_id":"…","raw":{}}}
    ← {"id":"…","ok":true,"result":{"download_id":"…"}}

    → {"id":"…","method":"download_status","params":{"download_id":"…"}}
    ← {"id":"…","ok":true,"result":{"state":"completed","progress":1.0,
         "message":"","local_paths":["C:\\\\…"]}}

    → {"id":"…","method":"cancel","params":{"download_id":"…"}}
    ← {"id":"…","ok":true,"result":{"cancelled":true}}

Error responses use ``{"id":"…","ok":false,"error":"…"}``.
"""

from __future__ import annotations

import json
import socket
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from vaultseek.models.interfaces.acquisition import SearchRequest, SearchResult

# Default port for VaultSeek's NDJSON companion (distinct from community HTTP 12339).
DEFAULT_RPC_PORT = 22024


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
    """Legacy empty client — prefer :class:`LocalSocketRpcClient`."""

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


class LocalSocketRpcClient:
    """TCP line-delimited JSON client for a Nicotine+ companion plugin.

    Connection and protocol errors never raise to callers — methods return
    empty hits / failed download states so acquisition stays resilient when
    Nicotine+ (or the companion) is offline.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = DEFAULT_RPC_PORT,
        *,
        timeout_seconds: float = 2.0,
    ) -> None:
        self._host = host
        self._port = port
        self._timeout = timeout_seconds

    @property
    def host(self) -> str:
        return self._host

    @property
    def port(self) -> int:
        return self._port

    def configure(self, host: str, port: int, *, timeout_seconds: float | None = None) -> None:
        self._host = host
        self._port = port
        if timeout_seconds is not None:
            self._timeout = timeout_seconds

    def search(self, request: SearchRequest) -> list[RpcSearchHit]:
        query_parts = [p for p in (request.artist, request.album, request.title) if p]
        params = {
            "query": " ".join(query_parts) if query_parts else (request.artist or ""),
            "artist": request.artist,
            "album": request.album,
            "title": request.title,
        }
        # SearchRequest may carry extra fields in future; keep raw passthrough soft.
        result = self._call("search", params)
        if result is None:
            return []
        hits_raw = result.get("hits") or []
        hits: list[RpcSearchHit] = []
        for item in hits_raw:
            if not isinstance(item, dict):
                continue
            hits.append(_hit_from_dict(item))
        return hits

    def enqueue_download(self, result_id: str, *, raw: dict[str, Any] | None = None) -> str:
        result = self._call(
            "enqueue_download",
            {"result_id": result_id, "raw": dict(raw or {})},
        )
        if result is None:
            return f"offline-{result_id}"
        download_id = result.get("download_id")
        return str(download_id) if download_id else f"offline-{result_id}"

    def download_status(self, download_id: str) -> RpcDownloadState:
        result = self._call("download_status", {"download_id": download_id})
        if result is None:
            return RpcDownloadState(
                download_id=download_id,
                state="failed",
                message=f"Nicotine+ RPC unreachable at {self._host}:{self._port}.",
            )
        paths_raw = result.get("local_paths") or []
        paths = tuple(Path(p) for p in paths_raw if p)
        return RpcDownloadState(
            download_id=download_id,
            state=str(result.get("state") or "failed"),
            progress=float(result.get("progress") or 0.0),
            message=str(result.get("message") or ""),
            local_paths=paths,
        )

    def cancel(self, download_id: str) -> bool:
        result = self._call("cancel", {"download_id": download_id})
        if result is None:
            return False
        return bool(result.get("cancelled", True))

    def _call(self, method: str, params: dict[str, Any]) -> dict[str, Any] | None:
        request_id = str(uuid4())
        payload = {"id": request_id, "method": method, "params": params}
        try:
            raw = self._exchange(payload)
        except (OSError, TimeoutError, json.JSONDecodeError, UnicodeError, ValueError):
            return None
        if not isinstance(raw, dict) or not raw.get("ok"):
            return None
        result = raw.get("result")
        return result if isinstance(result, dict) else {}

    def _exchange(self, payload: dict[str, Any]) -> dict[str, Any]:
        line = json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + "\n"
        with socket.create_connection((self._host, self._port), timeout=self._timeout) as sock:
            sock.settimeout(self._timeout)
            sock.sendall(line.encode("utf-8"))
            response_line = _recv_line(sock, self._timeout)
        data = json.loads(response_line)
        if not isinstance(data, dict):
            raise ValueError("RPC response must be a JSON object")
        return data


def _recv_line(sock: socket.socket, timeout: float) -> str:
    sock.settimeout(timeout)
    buf = bytearray()
    while True:
        chunk = sock.recv(4096)
        if not chunk:
            break
        buf.extend(chunk)
        if b"\n" in chunk:
            break
    if not buf:
        raise TimeoutError("empty RPC response")
    line, _, _ = bytes(buf).partition(b"\n")
    return line.decode("utf-8")


def _hit_from_dict(item: dict[str, Any]) -> RpcSearchHit:
    result_id = str(item.get("result_id") or item.get("id") or "")
    display = str(
        item.get("display_name")
        or item.get("file_path")
        or item.get("virtual_path")
        or result_id
        or "unknown"
    )
    size = item.get("size_bytes")
    if size is None:
        size = item.get("size")
    return RpcSearchHit(
        result_id=result_id or display,
        display_name=display,
        artist=item.get("artist"),
        album=item.get("album"),
        title=item.get("title"),
        format=item.get("format") or item.get("extension"),
        bit_depth=item.get("bit_depth"),
        size_bytes=int(size) if size is not None else None,
        track_count=item.get("track_count"),
        source_user=item.get("source_user") or item.get("username"),
        raw=dict(item),
    )


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
