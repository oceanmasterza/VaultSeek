"""Generic Subsonic media-server plugin."""

from __future__ import annotations

from typing import Any

from musicvault.models.interfaces.media_server import (
    LibrarySummary,
    MediaServerConfig,
    MediaServerPlugin,
    ServerCapabilities,
    ValidationIssue,
)
from musicvault.plugins.builtin.subsonic.client import SubsonicClient


class SubsonicPlugin:
    """Triggers a Subsonic-compatible library scan via the REST API."""

    plugin_id = "subsonic"
    display_name = "Subsonic"

    def __init__(self) -> None:
        self._client: SubsonicClient | None = None

    @property
    def capabilities(self) -> ServerCapabilities:
        return ServerCapabilities(trigger_rescan=True)

    def connect(self, config: MediaServerConfig) -> bool:
        if not config.server_url or not config.username:
            return False
        self._client = SubsonicClient(config.server_url, config.username, config.password)
        return self.test_connection()

    def test_connection(self) -> bool:
        if self._client is None:
            return False
        try:
            return self._client.ping()
        except Exception:  # noqa: BLE001 - connection probe
            return False

    def disconnect(self) -> None:
        self._client = None

    def trigger_rescan(self) -> bool:
        if self._client is None:
            return False
        try:
            return self._client.start_scan()
        except Exception:  # noqa: BLE001 - rescan best-effort
            return False

    def get_server_stats(self) -> dict[str, Any]:
        return {"connected": self._client is not None}

    def validate_library(self, local_library: LibrarySummary) -> list[ValidationIssue]:
        _ = local_library
        return []


def create_plugin() -> MediaServerPlugin:
    return SubsonicPlugin()
