"""Jellyfin media-server plugin — library refresh via REST."""

from __future__ import annotations

from typing import Any
from urllib.parse import urljoin

import requests

from musicvault.models.interfaces.media_server import (
    LibrarySummary,
    MediaServerConfig,
    MediaServerPlugin,
    ServerCapabilities,
    ValidationIssue,
)


class JellyfinPlugin:
    """Triggers a Jellyfin library scan using an API key (``token``)."""

    plugin_id = "jellyfin"
    display_name = "Jellyfin"

    def __init__(self) -> None:
        self._base: str | None = None
        self._token: str | None = None
        self._session = requests.Session()

    @property
    def capabilities(self) -> ServerCapabilities:
        return ServerCapabilities(trigger_rescan=True)

    def connect(self, config: MediaServerConfig) -> bool:
        if not config.server_url or not config.token:
            return False
        self._base = config.server_url.rstrip("/") + "/"
        self._token = config.token
        return self.test_connection()

    def test_connection(self) -> bool:
        if not self._base or not self._token:
            return False
        try:
            response = self._session.get(
                urljoin(self._base, "System/Info/Public"),
                timeout=15.0,
            )
            return response.ok
        except Exception:  # noqa: BLE001
            return False

    def disconnect(self) -> None:
        self._base = None
        self._token = None

    def trigger_rescan(self) -> bool:
        if not self._base or not self._token:
            return False
        try:
            response = self._session.post(
                urljoin(self._base, "Library/Refresh"),
                headers={"X-Emby-Token": self._token},
                timeout=30.0,
            )
            return response.ok
        except Exception:  # noqa: BLE001
            return False

    def get_server_stats(self) -> dict[str, Any]:
        return {"connected": bool(self._base and self._token)}

    def validate_library(self, local_library: LibrarySummary) -> list[ValidationIssue]:
        _ = local_library
        return []


def create_plugin() -> MediaServerPlugin:
    return JellyfinPlugin()
