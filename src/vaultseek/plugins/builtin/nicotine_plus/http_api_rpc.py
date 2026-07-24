"""HTTP RPC client for the community api-nicotine-plus plugin.

See https://github.com/palaueb/api-nicotine-plus (default ``127.0.0.1:12339``).
"""

from __future__ import annotations

import time
from pathlib import Path, PurePosixPath
from typing import Any

import requests

from vaultseek.models.interfaces.acquisition import SearchRequest
from vaultseek.plugins.builtin.nicotine_plus.rpc import RpcDownloadState, RpcSearchHit

DEFAULT_HTTP_PORT = 12339
DEFAULT_SEARCH_WAIT_SECONDS = 30.0
DEFAULT_SEARCH_POLL_INTERVAL = 1.5

_STATUS_MAP = {
    "finished": "completed",
    "complete": "completed",
    "completed": "completed",
    "queued": "queued",
    "getting status": "queued",
    "transferring": "downloading",
    "paused": "downloading",
    "cancelled": "cancelled",
    "filtered": "failed",
    "file not shared": "failed",
    "file not shared.": "failed",
    "user logged off": "failed",
    "connection closed": "failed",
    "connection timeout": "failed",
    "download folder error": "failed",
    "local file error": "failed",
}


class HttpApiRpcClient:
    """REST client for api-nicotine-plus — fails gracefully when offline."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = DEFAULT_HTTP_PORT,
        *,
        api_token: str = "",
        timeout_seconds: float = 5.0,
    ) -> None:
        self._host = host
        self._port = port
        self._api_token = api_token
        self._timeout = timeout_seconds
        self._session = requests.Session()

    @property
    def base_url(self) -> str:
        return f"http://{self._host}:{self._port}"

    def configure(
        self,
        host: str,
        port: int,
        *,
        api_token: str | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        self._host = host
        self._port = port
        if api_token is not None:
            self._api_token = api_token
        if timeout_seconds is not None:
            self._timeout = timeout_seconds

    def probe(self) -> bool:
        try:
            data = self._get("/health")
        except (OSError, requests.RequestException, ValueError):
            return False
        return data.get("status") == "ok"

    def is_soulseek_connected(self) -> bool:
        """True when api-nicotine-plus reports an active Soulseek login."""
        try:
            data = self._get("/status")
        except (OSError, requests.RequestException, ValueError):
            return False
        if not data.get("connected"):
            return False
        # login_status: 2 = logged in (plugin versions vary; treat truthy connected as ok)
        return True

    def search(
        self,
        request: SearchRequest,
        *,
        wait_seconds: float = DEFAULT_SEARCH_WAIT_SECONDS,
        poll_interval: float = DEFAULT_SEARCH_POLL_INTERVAL,
    ) -> list[RpcSearchHit]:
        """Start a Soulseek search and poll until results arrive or timeout.

        ``POST /search`` only *starts* the search; hits trickle in over several
        seconds. Fetching ``/search/results`` once immediately almost always
        returns an empty list.

        Soulseek occasionally returns zero hits for a full wait window even for
        popular tracks; when that happens we retry once with a simplified query
        (artist + title, dropping a redundant album token). Callers must treat
        ``ConnectionError`` as a transport problem (retry), not "song missing".
        """
        # Probe login before opening a search tab — searching while disconnected
        # burns the wait window and looks like a false "no results".
        if not self.is_soulseek_connected():
            raise ConnectionError(
                f"Nicotine+ Soulseek session not connected at {self.base_url}"
            )

        primary = _build_search_query(request)
        if not primary:
            return []

        hits = self._search_query(
            primary, wait_seconds=wait_seconds, poll_interval=poll_interval
        )
        if hits:
            return hits

        alternate = _simplified_search_query(request)
        if alternate and alternate.casefold() != primary.casefold():
            hits = self._search_query(
                alternate, wait_seconds=wait_seconds, poll_interval=poll_interval
            )
        return hits

    def _search_query(
        self,
        query: str,
        *,
        wait_seconds: float,
        poll_interval: float,
    ) -> list[RpcSearchHit]:
        try:
            started = self._post(
                "/search",
                {"query": query, "mode": "global", "switch_page": False},
            )
            token = started.get("token")
            if token is None:
                raise ValueError("search response missing token")
            token_i = int(token)
        except (OSError, requests.RequestException, ValueError) as exc:
            raise ConnectionError(f"Nicotine+ search start failed: {exc}") from exc

        deadline = time.monotonic() + max(0.0, float(wait_seconds))
        interval = max(0.2, float(poll_interval))
        hits: list[RpcSearchHit] = []
        last_count = -1
        stable_rounds = 0
        poll_errors = 0
        while True:
            try:
                results = self._get(
                    "/search/results",
                    params={"token": token_i, "limit": 200, "offset": 0},
                )
                poll_errors = 0
            except (OSError, requests.RequestException, ValueError):
                poll_errors += 1
                # Transient API blips are common — keep waiting until deadline.
                if poll_errors >= 8:
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                time.sleep(min(interval, remaining))
                continue

            hits = []
            for index, item in enumerate(results.get("items") or []):
                if not isinstance(item, dict):
                    continue
                hits.append(_hit_from_http_item(item, token=token_i, index=index))

            # Exit early once results stop growing (Soulseek trickle settled).
            if hits:
                if len(hits) == last_count:
                    stable_rounds += 1
                    if stable_rounds >= 2:
                        break
                else:
                    stable_rounds = 0
                    last_count = len(hits)

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(interval, remaining))

        try:
            self.close_search(token_i)
        except (OSError, requests.RequestException, ValueError):
            pass
        return hits

    def enqueue_download(self, result_id: str, *, raw: dict[str, Any] | None = None) -> str:
        """Queue a download; return ``username:virtual_path`` for status matching.

        Nicotine transfer rows expose Soulseek transfer tokens, not API search
        tokens — so ``token:index`` cannot be used to look up transfers.
        """
        raw = dict(raw or {})
        if ":" in result_id:
            token_s, index_s = result_id.split(":", 1)
            try:
                token = int(token_s)
                index = int(index_s)
                body: dict[str, Any] = {"token": token, "index": index}
                folder = raw.get("folder_path")
                if folder:
                    body["folder_path"] = str(folder)
                resp = self._post("/search/download", body)
                username = str(resp.get("username") or raw.get("username") or raw.get("source_user") or "")
                virtual_path = str(
                    resp.get("virtual_path")
                    or raw.get("file_path")
                    or raw.get("virtual_path")
                    or ""
                )
                # Close the Nicotine search tab once we've queued a download.
                try:
                    self.close_search(token)
                except (OSError, requests.RequestException, ValueError):
                    pass
                if username and virtual_path:
                    return f"{username}:{virtual_path}"
                return result_id
            except (ValueError, OSError, requests.RequestException):
                pass

        username = raw.get("username") or raw.get("source_user")
        virtual_path = raw.get("file_path") or raw.get("virtual_path")
        if username and virtual_path:
            try:
                body = {
                    "username": username,
                    "virtual_path": virtual_path,
                    "size": int(raw.get("size") or raw.get("size_bytes") or 0),
                }
                folder = raw.get("folder_path")
                if folder:
                    body["folder_path"] = str(folder)
                self._post(
                    "/downloads/enqueue",
                    body,
                )
                return f"{username}:{virtual_path}"
            except (OSError, requests.RequestException):
                return f"offline-{result_id}"
        return f"offline-{result_id}"

    def close_search(self, token: int) -> bool:
        """Ask api-nicotine-plus to close a search tab (best-effort)."""
        try:
            self._post("/search/close", {"token": int(token)})
            return True
        except (OSError, requests.RequestException, ValueError):
            return False

    def download_status(self, download_id: str) -> RpcDownloadState:
        try:
            payload = self._get("/downloads", params={"active_only": "false"})
        except (OSError, requests.RequestException, ValueError):
            return RpcDownloadState(
                download_id=download_id,
                state="failed",
                message=f"Nicotine+ HTTP API unreachable at {self.base_url}.",
            )

        items = payload.get("items") or []
        match = _find_transfer(download_id, items)
        if match is None:
            # Transfer list can lag enqueue by a tick — do not fail immediately.
            return RpcDownloadState(
                download_id=download_id,
                state="queued",
                message="waiting for Nicotine+ transfer list",
            )
        return _transfer_to_state(download_id, match)

    def cancel(self, download_id: str) -> bool:
        # api-nicotine-plus does not expose cancel endpoints yet.
        return False

    def _headers(self) -> dict[str, str]:
        if not self._api_token:
            return {}
        return {"Authorization": f"Bearer {self._api_token}"}

    def _get(self, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        response = self._session.get(
            f"{self.base_url}{path}",
            params=params,
            headers=self._headers(),
            timeout=self._timeout,
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("expected JSON object")
        return data

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        response = self._session.post(
            f"{self.base_url}{path}",
            json=body,
            headers=self._headers(),
            timeout=self._timeout,
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("expected JSON object")
        return data


def _hit_from_http_item(item: dict[str, Any], *, token: int, index: int) -> RpcSearchHit:
    file_path = str(item.get("file_path") or "")
    display = file_path or f"result-{token}-{index}"
    posix = PurePosixPath(file_path.replace("\\", "/")) if file_path else None
    parts = posix.parts if posix is not None else ()
    stem = posix.stem if posix is not None else None
    # Typical share layout: …/Artist/Album/Track.ext
    artist = None
    album = None
    if len(parts) >= 3:
        artist = parts[-3]
        album = parts[-2]
    elif len(parts) >= 2:
        album = parts[-2]
    attrs = item.get("file_attributes") or {}
    bit_depth = None
    bitrate = None
    if isinstance(attrs, dict):
        for key in ("bit_depth", "bitdepth", "bits"):
            if attrs.get(key) is not None:
                try:
                    bit_depth = int(attrs[key])
                except (TypeError, ValueError):
                    pass
        for key in ("bitrate", "br", "kbps"):
            if attrs.get(key) is not None:
                try:
                    bitrate = int(attrs[key])
                except (TypeError, ValueError):
                    pass
    extension = item.get("extension")
    if not extension and file_path:
        name = PurePosixPath(file_path.replace("\\", "/")).name
        if "." in name:
            extension = name.rsplit(".", 1)[-1]
    raw = {**item, "token": token, "index": index}
    if bitrate is not None:
        raw["bitrate"] = bitrate
    if extension:
        raw["extension"] = extension
    return RpcSearchHit(
        result_id=f"{token}:{index}",
        display_name=display,
        artist=artist,
        album=album,
        title=stem,
        format=str(extension or ""),
        bit_depth=bit_depth,
        size_bytes=int(item.get("size") or 0) or None,
        source_user=str(item.get("username") or "") or None,
        raw=raw,
    )


def _build_search_query(request: SearchRequest) -> str:
    """Join artist/album/title, dropping a redundant album when it equals artist."""
    parts: list[str] = []
    artist = (request.artist or "").strip()
    album = (request.album or "").strip()
    title = (request.title or "").strip()
    if artist:
        parts.append(artist)
    if album and album.casefold() != artist.casefold():
        parts.append(album)
    if title:
        parts.append(title)
    return " ".join(parts).strip()


def _simplified_search_query(request: SearchRequest) -> str:
    """Artist + title only — often yields hits when the full query is empty."""
    parts = [p for p in ((request.artist or "").strip(), (request.title or "").strip()) if p]
    return " ".join(parts).strip()


def _find_transfer(download_id: str, items: list[Any]) -> dict[str, Any] | None:
    if ":" not in download_id:
        return None
    left, right = download_id.split(":", 1)
    for item in items:
        if not isinstance(item, dict):
            continue
        username = str(item.get("username") or "")
        virtual = str(item.get("virtual_path") or item.get("file_path") or "")
        if username == left and virtual == right:
            return item
    # Fallback: match by filename when path separators differ.
    right_name = PurePosixPath(right.replace("\\", "/")).name
    if right_name:
        for item in items:
            if not isinstance(item, dict):
                continue
            if str(item.get("username") or "") != left:
                continue
            virtual = str(item.get("virtual_path") or item.get("file_path") or "")
            if PurePosixPath(virtual.replace("\\", "/")).name == right_name:
                return item
    return None


def _transfer_to_state(download_id: str, item: dict[str, Any]) -> RpcDownloadState:
    status = str(item.get("status") or "")
    state = _STATUS_MAP.get(status.casefold(), "downloading")
    progress = float(item.get("progress_pct") or 0.0) / 100.0
    if state == "completed":
        progress = 1.0
    local_paths: tuple[Path, ...] = ()
    if state == "completed":
        folder = item.get("folder_path")
        virtual = item.get("virtual_path") or item.get("file_path")
        if folder and virtual:
            name = PurePosixPath(str(virtual).replace("\\", "/")).name
            local_paths = (Path(str(folder)) / name,)
    return RpcDownloadState(
        download_id=download_id,
        state=state,
        progress=progress,
        message=status,
        local_paths=local_paths,
    )
