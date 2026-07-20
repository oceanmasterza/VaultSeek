"""Lyrion Music Server (formerly Logitech Media Server) plugin."""

from __future__ import annotations

from typing import Any
from urllib.parse import urljoin

import requests

from vaultseek.models.interfaces.media_server import (
    LibrarySummary,
    MediaServerConfig,
    MediaServerPlugin,
    ServerCapabilities,
    ValidationIssue,
)


class LyrionPlugin:
    """Triggers a Lyrion / LMS library rescan via JSON-RPC ``jsonrpc.js``.

    Auth is optional (``token`` or username/password unused for many local
    installs). ``server_url`` should be the LMS HTTP base
    (e.g. ``http://localhost:9000``).
    """

    plugin_id = "lyrion"
    display_name = "Lyrion Music Server"

    def __init__(self) -> None:
        self._base: str | None = None
        self._session = requests.Session()

    @property
    def capabilities(self) -> ServerCapabilities:
        return ServerCapabilities(trigger_rescan=True)

    def connect(self, config: MediaServerConfig) -> bool:
        if not config.server_url:
            return False
        self._base = config.server_url.rstrip("/") + "/"
        return self.test_connection()

    def _rpc(self, command: list[str]) -> requests.Response | None:
        if not self._base:
            return None
        payload = {"id": 1, "method": "slim.request", "params": ["", command]}
        return self._session.post(
            urljoin(self._base, "jsonrpc.js"),
            json=payload,
            timeout=30.0,
        )

    def test_connection(self) -> bool:
        if not self._base:
            return False
        try:
            response = self._rpc(["version", "?"])
            return response is not None and response.ok
        except Exception:  # noqa: BLE001
            return False

    def disconnect(self) -> None:
        self._base = None

    def trigger_rescan(self) -> bool:
        if not self._base:
            return False
        try:
            # Full rescan; "rescan" / "wiimplaylists" variants exist by version.
            response = self._rpc(["rescan"])
            if response is not None and response.ok:
                return True
            response = self._rpc(["rescan", "playlists"])
            return response is not None and response.ok
        except Exception:  # noqa: BLE001
            return False

    def get_server_stats(self) -> dict[str, Any]:
        return {"connected": bool(self._base)}

    def validate_library(self, local_library: LibrarySummary) -> list[ValidationIssue]:
        _ = local_library
        return []


def create_plugin() -> MediaServerPlugin:
    return LyrionPlugin()
