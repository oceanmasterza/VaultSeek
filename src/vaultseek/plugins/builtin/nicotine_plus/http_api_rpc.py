"""HTTP RPC client for the community api-nicotine-plus plugin.

See https://github.com/palaueb/api-nicotine-plus (default ``127.0.0.1:12339``).
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any

import requests

from vaultseek.models.interfaces.acquisition import SearchRequest
from vaultseek.plugins.builtin.nicotine_plus.rpc import RpcDownloadState, RpcSearchHit

DEFAULT_HTTP_PORT = 12339

_STATUS_MAP = {
    "finished": "completed",
    "queued": "queued",
    "getting status": "queued",
    "transferring": "downloading",
    "paused": "downloading",
    "cancelled": "cancelled",
    "filtered": "failed",
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

    def search(self, request: SearchRequest) -> list[RpcSearchHit]:
        query_parts = [p for p in (request.artist, request.album, request.title) if p]
        query = " ".join(query_parts) if query_parts else (request.artist or "")
        if not query.strip():
            return []
        try:
            started = self._post("/search", {"query": query, "mode": "global"})
            token = started.get("token")
            if token is None:
                return []
            results = self._get(
                "/search/results",
                params={"token": int(token), "limit": 200, "offset": 0},
            )
        except (OSError, requests.RequestException, ValueError):
            return []

        hits: list[RpcSearchHit] = []
        for index, item in enumerate(results.get("items") or []):
            if not isinstance(item, dict):
                continue
            hits.append(_hit_from_http_item(item, token=int(token), index=index))
        return hits

    def enqueue_download(self, result_id: str, *, raw: dict[str, Any] | None = None) -> str:
        raw = dict(raw or {})
        if ":" in result_id:
            token_s, index_s = result_id.split(":", 1)
            try:
                token = int(token_s)
                index = int(index_s)
                self._post("/search/download", {"token": token, "index": index})
                return result_id
            except (ValueError, OSError, requests.RequestException):
                pass

        username = raw.get("username") or raw.get("source_user")
        virtual_path = raw.get("file_path") or raw.get("virtual_path")
        if username and virtual_path:
            try:
                self._post(
                    "/downloads/enqueue",
                    {
                        "username": username,
                        "virtual_path": virtual_path,
                        "size": int(raw.get("size") or raw.get("size_bytes") or 0),
                    },
                )
                return f"{username}:{virtual_path}"
            except (OSError, requests.RequestException):
                return f"offline-{result_id}"
        return f"offline-{result_id}"

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
            return RpcDownloadState(
                download_id=download_id,
                state="failed",
                message="download not found in Nicotine+ transfers",
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
    return RpcSearchHit(
        result_id=f"{token}:{index}",
        display_name=display,
        title=PurePosixPath(file_path.replace("\\", "/")).stem if file_path else None,
        format=str(item.get("extension") or ""),
        size_bytes=int(item.get("size") or 0) or None,
        source_user=str(item.get("username") or "") or None,
        raw={**item, "token": token, "index": index},
    )


def _find_transfer(download_id: str, items: list[Any]) -> dict[str, Any] | None:
    if ":" not in download_id:
        return None
    left, right = download_id.split(":", 1)
    try:
        token = int(left)
        for item in items:
            if isinstance(item, dict) and item.get("token") == token:
                return item
    except ValueError:
        pass
    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("username") == left and item.get("virtual_path") == right:
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
