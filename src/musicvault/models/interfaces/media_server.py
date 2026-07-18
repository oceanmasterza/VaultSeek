"""Media server plugin protocol — Subsonic / Jellyfin / Plex / etc.

See docs/architecture/05-plugin-api.md ("Media Server Plugins"). Phase 15
ships the protocol plus Navidrome (Subsonic + optional read-only DB),
generic Subsonic, Jellyfin, and Plex rescan plugins. Full validation
audits for every server stay deferred.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ServerCapabilities:
    """What a media-server plugin can do beyond a basic rescan trigger."""

    direct_db_access: bool = False
    trigger_rescan: bool = True
    validate_metadata: bool = False
    detect_duplicates: bool = False
    get_missing_artwork: bool = False
    get_broken_paths: bool = False


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """One finding from :meth:`MediaServerPlugin.validate_library`."""

    severity: Literal["error", "warning", "info"]
    category: str
    message: str
    server_entity_id: str | None = None
    local_entity_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class MediaServerConfig:
    """Connection settings for one configured media-server plugin instance.

    Persisted in ``media_server_state`` (url / db_path / JSON config blob).
    Credentials live in the JSON ``config`` column — never logged.
    """

    library_id: UUID
    plugin_id: str
    server_url: str = ""
    db_path: str | None = None
    username: str = ""
    password: str = ""
    token: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class LibrarySummary:
    """Minimal local-library snapshot for optional server-side validation."""

    track_count: int
    album_count: int = 0
    artist_count: int = 0


class MediaServerPlugin(Protocol):
    """A pluggable media-server integration."""

    plugin_id: str
    display_name: str

    @property
    def capabilities(self) -> ServerCapabilities: ...

    def connect(self, config: MediaServerConfig) -> bool: ...

    def test_connection(self) -> bool: ...

    def disconnect(self) -> None: ...

    def trigger_rescan(self) -> bool: ...

    def get_server_stats(self) -> dict[str, Any]: ...

    def validate_library(self, local_library: LibrarySummary) -> list[ValidationIssue]: ...
