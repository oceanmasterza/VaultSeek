"""Funkwhale media-server plugin — instance ping + library scan API."""

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


class FunkwhalePlugin:
    """Uses a Funkwhale JWT / OAuth token (``MediaServerConfig.token``).

    ``extra["library_id"]`` may select a specific library UUID for scan;
    without it, tries the manage-library scan endpoint.
    """

    plugin_id = "funkwhale"
    display_name = "Funkwhale"

    def __init__(self) -> None:
        self._base: str | None = None
        self._token: str | None = None
        self._library_uuid: str | None = None
        self._session = requests.Session()

    @property
    def capabilities(self) -> ServerCapabilities:
        return ServerCapabilities(trigger_rescan=True)

    def connect(self, config: MediaServerConfig) -> bool:
        if not config.server_url or not config.token:
            return False
        self._base = config.server_url.rstrip("/") + "/"
        self._token = config.token
        lib = config.extra.get("library_id")
        self._library_uuid = str(lib) if lib else None
        return self.test_connection()

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}", "Accept": "application/json"}

    def test_connection(self) -> bool:
        if not self._base or not self._token:
            return False
        for path in ("api/v1/instance/", "api/v1/nodeinfo/2.0/", "api/v2/instance/nodeinfo/2.0/"):
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
        self._library_uuid = None

    def trigger_rescan(self) -> bool:
        if not self._base or not self._token:
            return False
        paths: list[str] = []
        if self._library_uuid:
            paths.append(f"api/v1/libraries/{self._library_uuid}/scan/")
        paths.extend(
            (
                "api/v1/manage/libraries/scan/",
                "api/v1/libraries/scan/",
            )
        )
        for path in paths:
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
        return {
            "connected": bool(self._base and self._token),
            "library_id": self._library_uuid,
        }

    def validate_library(self, local_library: LibrarySummary) -> list[ValidationIssue]:
        _ = local_library
        return []


def create_plugin() -> MediaServerPlugin:
    return FunkwhalePlugin()
