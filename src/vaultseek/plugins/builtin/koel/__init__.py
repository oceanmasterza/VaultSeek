"""Koel media-server plugin — JWT API ping + best-effort sync trigger."""

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


class KoelPlugin:
    """Connects with a Koel API token (``MediaServerConfig.token``).

    ``test_connection`` hits ``GET /api/overview`` (or ``/api/data``).
    Rescan tries ``POST /api/sync`` then ``POST /api/songs/sync`` — Koel
    versions differ; failure is non-fatal for the worker.
    """

    plugin_id = "koel"
    display_name = "Koel"

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

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}", "Accept": "application/json"}

    def test_connection(self) -> bool:
        if not self._base or not self._token:
            return False
        for path in ("api/overview", "api/data", "api/me"):
            try:
                response = self._session.get(
                    urljoin(self._base, path),
                    headers=self._headers(),
                    timeout=15.0,
                )
                if response.ok:
                    return True
            except Exception:  # noqa: BLE001
                continue
        return False

    def disconnect(self) -> None:
        self._base = None
        self._token = None

    def trigger_rescan(self) -> bool:
        if not self._base or not self._token:
            return False
        for path in ("api/sync", "api/songs/sync", "api/library/scan"):
            try:
                response = self._session.post(
                    urljoin(self._base, path),
                    headers=self._headers(),
                    timeout=60.0,
                )
                if response.ok or response.status_code in {202, 204}:
                    return True
            except Exception:  # noqa: BLE001
                continue
        return False

    def get_server_stats(self) -> dict[str, Any]:
        return {"connected": bool(self._base and self._token)}

    def validate_library(self, local_library: LibrarySummary) -> list[ValidationIssue]:
        _ = local_library
        return []


def create_plugin() -> MediaServerPlugin:
    return KoelPlugin()
