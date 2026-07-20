"""Navidrome media-server plugin (Subsonic API + optional read-only DB)."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from vaultseek.models.interfaces.media_server import (
    LibrarySummary,
    MediaServerConfig,
    MediaServerPlugin,
    ServerCapabilities,
    ValidationIssue,
)
from vaultseek.plugins.builtin.subsonic.client import SubsonicClient


class NavidromePlugin:
    """Navidrome integration: rescan via Subsonic; optional RO SQLite stats."""

    plugin_id = "navidrome"
    display_name = "Navidrome"

    def __init__(self) -> None:
        self._client: SubsonicClient | None = None
        self._db: sqlite3.Connection | None = None

    @property
    def capabilities(self) -> ServerCapabilities:
        return ServerCapabilities(
            direct_db_access=self._db is not None,
            trigger_rescan=True,
            validate_metadata=self._db is not None,
            get_missing_artwork=self._db is not None,
        )

    def connect(self, config: MediaServerConfig) -> bool:
        if not config.server_url or not config.username:
            return False
        self._client = SubsonicClient(config.server_url, config.username, config.password)
        self._db = None
        if config.db_path:
            path = Path(config.db_path)
            if path.is_file():
                uri = f"file:{path.resolve().as_posix()}?mode=ro"
                self._db = sqlite3.connect(uri, uri=True)
        return self.test_connection()

    def test_connection(self) -> bool:
        if self._client is None:
            return False
        try:
            return self._client.ping()
        except Exception:  # noqa: BLE001
            return False

    def disconnect(self) -> None:
        if self._db is not None:
            self._db.close()
            self._db = None
        self._client = None

    def trigger_rescan(self) -> bool:
        if self._client is None:
            return False
        try:
            return self._client.start_scan()
        except Exception:  # noqa: BLE001
            return False

    def get_server_stats(self) -> dict[str, Any]:
        stats: dict[str, Any] = {
            "connected": self._client is not None,
            "db_open": self._db is not None,
        }
        if self._db is None:
            return stats
        try:
            row = self._db.execute("SELECT COUNT(*) FROM media_file").fetchone()
            stats["media_file_count"] = int(row[0]) if row else 0
        except sqlite3.Error:
            stats["media_file_count"] = None
        return stats

    def validate_library(self, local_library: LibrarySummary) -> list[ValidationIssue]:
        if self._db is None:
            return []
        issues: list[ValidationIssue] = []
        try:
            row = self._db.execute("SELECT COUNT(*) FROM media_file").fetchone()
            server_count = int(row[0]) if row else 0
            if local_library.track_count and abs(server_count - local_library.track_count) > max(
                10, local_library.track_count // 10
            ):
                issues.append(
                    ValidationIssue(
                        severity="warning",
                        category="count_mismatch",
                        message=(
                            f"Local library has {local_library.track_count} tracks; "
                            f"Navidrome reports {server_count} media files"
                        ),
                    )
                )
        except sqlite3.Error as exc:
            issues.append(
                ValidationIssue(
                    severity="info",
                    category="db_query",
                    message=f"Could not query navidrome.db: {exc}",
                )
            )
        return issues


def create_plugin() -> MediaServerPlugin:
    return NavidromePlugin()
