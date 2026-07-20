"""Plex media-server plugin — library refresh via Plex API."""

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


class PlexPlugin:
    """Triggers a Plex library section refresh.

    ``extra["section_id"]`` selects the library section (default ``1``).
    Auth uses a Plex token (``MediaServerConfig.token``).
    """

    plugin_id = "plex"
    display_name = "Plex"

    def __init__(self) -> None:
        self._base: str | None = None
        self._token: str | None = None
        self._section_id: str = "1"
        self._session = requests.Session()

    @property
    def capabilities(self) -> ServerCapabilities:
        return ServerCapabilities(trigger_rescan=True)

    def connect(self, config: MediaServerConfig) -> bool:
        if not config.server_url or not config.token:
            return False
        self._base = config.server_url.rstrip("/") + "/"
        self._token = config.token
        section = config.extra.get("section_id", "1")
        self._section_id = str(section)
        return self.test_connection()

    def test_connection(self) -> bool:
        if not self._base or not self._token:
            return False
        try:
            response = self._session.get(
                urljoin(self._base, "identity"),
                headers={"X-Plex-Token": self._token},
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
            response = self._session.get(
                urljoin(self._base, f"library/sections/{self._section_id}/refresh"),
                headers={"X-Plex-Token": self._token},
                timeout=30.0,
            )
            return response.ok
        except Exception:  # noqa: BLE001
            return False

    def get_server_stats(self) -> dict[str, Any]:
        return {
            "connected": bool(self._base and self._token),
            "section_id": self._section_id,
        }

    def validate_library(self, local_library: LibrarySummary) -> list[ValidationIssue]:
        _ = local_library
        return []


def create_plugin() -> MediaServerPlugin:
    return PlexPlugin()
