# 05 — Plugin API

## Design Goals

1. **Extensible from day one** — core never hard-codes MusicBrainz, Navidrome, etc.
2. **Type-safe contracts** — plugins implement Python `Protocol` classes
3. **Standard discovery** — `pyproject.toml` entry points (`importlib.metadata`)
4. **Configurable** — per-plugin JSON config stored in `plugin_state` table
5. **Isolated failures** — a broken plugin must not crash the application
6. **No remote code execution** — plugins are local Python packages only

## Plugin Types

| Type | Protocol | Purpose |
|------|----------|---------|
| Metadata Provider | `MetadataProvider` | Look up artist/album/track metadata |
| Fingerprint Provider | `FingerprintProvider` | Generate fingerprints, lookup AcoustID |
| Artwork Provider | `ArtworkProvider` | Download album/track artwork |
| Media Server | `MediaServerPlugin` | Integrate with Navidrome, Jellyfin, Plex |
| Report Exporter | `ReportExporter` | Custom report output formats |
| Cloud Backup | `CloudBackupPlugin` | Backup library database and config |

A single plugin package may implement multiple protocols.

## Base Plugin Protocol

```python
from typing import Protocol, Any

class PluginInfo:
    id: str              # Unique identifier, e.g. "musicbrainz"
    name: str            # Display name, e.g. "MusicBrainz"
    version: str         # Semver
    author: str
    description: str
    website: str | None
    plugin_type: str     # "metadata", "artwork", "media_server", etc.

class Plugin(Protocol):
    @property
    def info(self) -> PluginInfo: ...

    def initialize(self, config: dict[str, Any]) -> None:
        """Called once when plugin is loaded. Validate config, setup clients."""
        ...

    def shutdown(self) -> None:
        """Called on application exit. Close connections, flush caches."""
        ...

    def is_available(self) -> bool:
        """Return False if dependencies missing (e.g., no API key)."""
        ...

    def get_config_schema(self) -> dict[str, Any]:
        """JSON Schema for plugin configuration UI."""
        ...
```

## Metadata Provider

```python
@dataclass(frozen=True)
class MetadataQuery:
    """Input for metadata lookup."""
    artist: str | None = None
    album: str | None = None
    title: str | None = None
    duration_ms: int | None = None
    mb_recording_id: str | None = None
    mb_release_id: str | None = None
    acoustid_id: str | None = None
    fingerprint: bytes | None = None
    fingerprint_duration: float | None = None

@dataclass(frozen=True)
class MetadataResult:
    """Standardized metadata from any provider."""
    source: str                          # Plugin ID
    confidence: float                    # 0.0–1.0
    artist: str | None = None
    album_artist: str | None = None
    album: str | None = None
    title: str | None = None
    track_number: int | None = None
    disc_number: int | None = None
    total_tracks: int | None = None
    year: int | None = None
    release_date: str | None = None
    genre: str | None = None
    composer: str | None = None
    label: str | None = None
    catalog_number: str | None = None
    country: str | None = None
    mb_artist_id: str | None = None
    mb_release_id: str | None = None
    mb_release_group_id: str | None = None
    mb_recording_id: str | None = None
    mb_track_id: str | None = None
    is_compilation: bool = False
    replaygain_track: float | None = None
    replaygain_album: float | None = None
    raw_data: dict[str, Any] | None = None  # Provider-specific extras

class MetadataProvider(Plugin, Protocol):
    def lookup_by_fingerprint(
        self,
        fingerprint: bytes,
        duration: float,
    ) -> list[MetadataResult]: ...

    def lookup_by_tags(self, query: MetadataQuery) -> list[MetadataResult]: ...

    def lookup_by_id(self, mbid: str, id_type: str) -> MetadataResult | None: ...

    def search(
        self,
        query: str,
        entity_type: Literal["artist", "album", "recording"],
        limit: int = 10,
    ) -> list[MetadataResult]: ...
```

## Fingerprint Provider

```python
@dataclass(frozen=True)
class FingerprintData:
    chromaprint: bytes
    duration: float
    acoustid_id: str | None = None
    acoustid_score: float | None = None

class FingerprintProvider(Plugin, Protocol):
    def generate(self, file_path: str) -> FingerprintData: ...

    def lookup(
        self,
        fingerprint: bytes,
        duration: float,
    ) -> list[MetadataResult]: ...
```

## Artwork Provider

```python
@dataclass(frozen=True)
class ArtworkQuery:
    mb_release_id: str | None = None
    mb_release_group_id: str | None = None
    artist: str | None = None
    album: str | None = None
    min_width: int = 500
    min_height: int = 500

@dataclass(frozen=True)
class ArtworkResult:
    source: str
    data: bytes
    mime_type: str
    width: int
    height: int
    source_id: str | None = None
    is_front: bool = True

class ArtworkProvider(Plugin, Protocol):
    def search(self, query: ArtworkQuery) -> list[ArtworkResult]: ...

    def get_best(self, query: ArtworkQuery) -> ArtworkResult | None: ...
```

## Media Server Plugin

```python
@dataclass(frozen=True)
class ServerConnection:
    url: str
    username: str | None = None
    password: str | None = None
    token: str | None = None

@dataclass(frozen=True)
class ServerAlbum:
    server_id: str
    title: str
    artist: str
    track_count: int
    mb_release_id: str | None = None

@dataclass(frozen=True)
class ValidationIssue:
    severity: Literal["error", "warning", "info"]
    category: str          # "missing_metadata", "duplicate", "path_mismatch"
    message: str
    server_album_id: str | None = None
    local_album_id: int | None = None

class MediaServerPlugin(Plugin, Protocol):
    def connect(self, connection: ServerConnection) -> bool: ...

    def test_connection(self) -> bool: ...

    def get_albums(self) -> list[ServerAlbum]: ...

    def validate_library(
        self,
        local_albums: Sequence[Album],
    ) -> list[ValidationIssue]: ...

    def trigger_rescan(self) -> bool: ...

    def get_server_stats(self) -> dict[str, Any]: ...
```

## Plugin Manager

```python
class PluginManager:
    def __init__(self, plugin_state_repo: PluginStateRepository) -> None: ...

    def discover(self) -> list[PluginInfo]:
        """Find all installed plugins via entry points."""
        ...

    def load(self, plugin_id: str) -> Plugin:
        """Load and initialize a specific plugin."""
        ...

    def load_all(self) -> None:
        """Load all enabled plugins."""
        ...

    def enable(self, plugin_id: str) -> None: ...
    def disable(self, plugin_id: str) -> None: ...

    def get_metadata_providers(self) -> list[MetadataProvider]:
        """Return all loaded metadata providers, priority-ordered."""
        ...

    def get_artwork_providers(self) -> list[ArtworkProvider]: ...
    def get_media_servers(self) -> list[MediaServerPlugin]: ...

    def configure(self, plugin_id: str, config: dict[str, Any]) -> None: ...
    def get_config(self, plugin_id: str) -> dict[str, Any]: ...
```

### Discovery Mechanism

Plugins are registered via `pyproject.toml` entry points:

```toml
[project.entry-points."musicvault.plugins"]
musicbrainz = "musicvault.plugins.builtin.musicbrainz:MusicBrainzPlugin"
acoustid = "musicvault.plugins.builtin.acoustid:AcoustIDPlugin"
navidrome = "musicvault.plugins.builtin.navidrome:NavidromePlugin"
cover_art_archive = "musicvault.plugins.builtin.cover_art_archive:CoverArtArchivePlugin"
```

Third-party plugins install their own entry points:

```toml
[project.entry-points."musicvault.plugins"]
discogs = "discogs_musicvault:DiscogsPlugin"
```

### Plugin Loading Sequence

```
App startup
  → PluginManager.discover()
    → importlib.metadata.entry_points(group="musicvault.plugins")
    → For each entry point:
        → Load PluginInfo from entry point module
        → Check plugin_state.enabled in DB
        → If enabled: PluginManager.load(plugin_id)
            → entry_point.load()()
            → plugin.initialize(config)
            → Register in type-specific lists
```

### Error Isolation

```python
def load(self, plugin_id: str) -> Plugin:
    try:
        plugin = self._entry_points[plugin_id].load()()
        config = self._state_repo.get_config(plugin_id)
        plugin.initialize(config)
        return plugin
    except Exception as e:
        logger.error(f"Failed to load plugin {plugin_id}: {e}")
        self._failed_plugins[plugin_id] = str(e)
        raise PluginLoadError(plugin_id, e) from e
```

Failed plugins are logged and shown in the Plugins settings page as disabled with error message. The rest of the application continues normally.

## Built-in Plugins

### MusicBrainz (Phase 6)

| Property | Value |
|----------|-------|
| ID | `musicbrainz` |
| Type | Metadata Provider |
| API | https://musicbrainz.org/ws/2/ |
| Rate limit | 1 request/second |
| Auth | User-agent required; optional API key |
| Lookup methods | Fingerprint (via AcoustID), tags, MBID |

### AcoustID / Chromaprint (Phase 5)

| Property | Value |
|----------|-------|
| ID | `acoustid` |
| Type | Fingerprint Provider |
| Dependencies | `pyacoustid`, `fpcalc` (Chromaprint binary) |
| API | https://api.acoustid.org/v2/lookup |
| Auth | API key required (free registration) |

### Cover Art Archive (Phase 9)

| Property | Value |
|----------|-------|
| ID | `cover_art_archive` |
| Type | Artwork Provider |
| API | https://coverartarchive.org/ |
| Auth | None required |
| Resolution | Up to 1200×1200 (front cover) |

### Navidrome (Phase 13)

| Property | Value |
|----------|-------|
| ID | `navidrome` |
| Type | Media Server |
| API | Navidrome Subsonic-compatible API |
| Auth | Username + password (token-based) |
| Features | Validate library, detect server-side duplicates, trigger rescan |

### Discogs (Future)

| Property | Value |
|----------|-------|
| ID | `discogs` |
| Type | Metadata Provider + Artwork Provider |
| API | https://api.discogs.com/ |
| Auth | User token required |
| Status | Planned plugin, not built-in |

## Plugin Configuration Schema

Each plugin provides a JSON Schema for its settings, rendered in the Settings → Plugins UI:

```json
{
  "$schema": "http://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "properties": {
    "api_key": {
      "type": "string",
      "title": "API Key",
      "description": "AcoustID API key (free at https://acoustid.org/api-key)"
    },
    "rate_limit_ms": {
      "type": "integer",
      "title": "Rate Limit (ms)",
      "default": 1000,
      "minimum": 100
    },
    "cache_ttl_hours": {
      "type": "integer",
      "title": "Cache TTL (hours)",
      "default": 168
    }
  },
  "required": ["api_key"]
}
```

## Plugin Priority & Chaining

When multiple plugins of the same type are enabled, the `PluginManager` returns them in priority order (user-configurable in Settings):

```
Metadata lookup chain:
  1. acoustid (fingerprint → MusicBrainz recording)
  2. musicbrainz (tag-based search)
  3. discogs (fallback, if installed)

Artwork lookup chain:
  1. cover_art_archive (by MB release ID)
  2. discogs (by artist + album search)
```

The `MetadataService` tries each provider in order until a result with confidence ≥ threshold is found.

## Third-Party Plugin Development

### Minimum Plugin Package Structure

```
my-musicvault-plugin/
├── pyproject.toml
├── src/
│   └── my_plugin/
│       ├── __init__.py
│       └── plugin.py     # Implements MetadataProvider (or other protocol)
└── README.md
```

### Example Third-Party Plugin

```python
from musicvault.plugins.base import PluginInfo
from musicvault.domain.interfaces.metadata import MetadataProvider, MetadataQuery, MetadataResult

class MyPlugin:
    @property
    def info(self) -> PluginInfo:
        return PluginInfo(
            id="my_plugin",
            name="My Custom Provider",
            version="1.0.0",
            author="Developer",
            description="Custom metadata source",
            website=None,
            plugin_type="metadata",
        )

    def initialize(self, config: dict) -> None:
        self._api_key = config.get("api_key", "")

    def shutdown(self) -> None: ...

    def is_available(self) -> bool:
        return bool(self._api_key)

    def get_config_schema(self) -> dict:
        return {"type": "object", "properties": {"api_key": {"type": "string"}}}

    def lookup_by_fingerprint(self, fingerprint, duration) -> list[MetadataResult]:
        return []

    def lookup_by_tags(self, query: MetadataQuery) -> list[MetadataResult]:
        # Custom lookup logic
        ...

    def lookup_by_id(self, mbid, id_type) -> MetadataResult | None:
        return None

    def search(self, query, entity_type, limit=10) -> list[MetadataResult]:
        return []
```

### Publishing

```toml
[project]
name = "my-musicvault-plugin"
dependencies = ["musicvault>=1.0.0"]

[project.entry-points."musicvault.plugins"]
my_plugin = "my_plugin.plugin:MyPlugin"
```

Install: `pip install my-musicvault-plugin` — auto-discovered on next MusicVault startup.

## Caching

All plugins share a common caching layer:

| Cache | Location | TTL | Purpose |
|-------|----------|-----|---------|
| MusicBrainz responses | `%APPDATA%/MusicVault/cache/musicbrainz/` | 7 days | Avoid repeat API calls |
| AcoustID lookups | `%APPDATA%/MusicVault/cache/acoustid/` | 30 days | Fingerprints don't change |
| Artwork images | `%APPDATA%/MusicVault/cache/artwork/` | 30 days | Downloaded images |
| Plugin config | `plugin_state` DB table | Permanent | Per-plugin settings |

Cache keys are SHA-256 hashes of the query parameters. Plugins use `CacheManager` from infrastructure, not their own cache implementations.
