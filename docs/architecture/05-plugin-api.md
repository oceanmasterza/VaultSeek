# 05 — Plugin API (v2)

> **Revision**: v2 — Expanded media servers, metadata arbitration, direct DB access.
> See [10-revision-v2.md](10-revision-v2.md).

## Plugin Types

| Type | Protocol | Purpose |
|------|----------|---------|
| Metadata Provider | `MetadataProvider` | Artist/album/track lookup with confidence |
| Fingerprint Provider | `FingerprintProvider` | Chromaprint + AcoustID |
| Artwork Provider | `ArtworkProvider` | Download album artwork |
| Media Server | `MediaServerPlugin` | Navidrome, Jellyfin, Plex, etc. |
| Filename Parser | `FilenameParserPlugin` | Extract metadata from filenames |
| Report Exporter | `ReportExporter` | Custom report formats |

## Metadata Provider Protocol

Every provider returns **per-field confidence scores**, not just values:

```python
@dataclass(frozen=True)
class ProviderFieldResult:
    field: str
    value: str | int | None
    confidence: float                # 0.0–1.0

@dataclass(frozen=True)
class ProviderResult:
    provider_id: str
    fields: list[ProviderFieldResult]
    overall_confidence: float        # min(field confidences)
    lookup_method: str               # "fingerprint", "tags", "id", "search"
    raw_response: dict[str, Any] | None

class MetadataProvider(Plugin, Protocol):
    PRIORITY: int                    # Lower = higher priority (default chain order)

    def lookup_by_fingerprint(
        self, fingerprint: bytes, duration: float,
    ) -> ProviderResult | None: ...

    def lookup_by_tags(self, query: MetadataQuery) -> ProviderResult | None: ...

    def lookup_by_id(self, external_id: str, id_type: str) -> ProviderResult | None: ...

    def search(
        self, query: str,
        entity_type: Literal["artist", "album", "recording"],
        limit: int = 10,
    ) -> list[ProviderResult]: ...
```

The `MetadataArbitrator` (application layer) calls all providers and selects best per-field. Plugins do not know about each other.

## Default Provider Priority

| Priority | Provider | Typical Confidence | Lookup Methods |
|----------|----------|-------------------|----------------|
| 10 | MusicBrainz | 0.85–0.99 | Fingerprint, tags, MBID |
| 20 | Discogs | 0.70–0.95 | Search, release ID |
| 50 | Local Tags | 0.60–0.90 | Embedded metadata |
| 90 | Filename Parser | 0.30–0.70 | Regex extraction |

User can reorder in Settings → Metadata Providers.

## Built-in Metadata Providers

### MusicBrainz

| Property | Value |
|----------|-------|
| ID | `musicbrainz` |
| Priority | 10 |
| API | `https://musicbrainz.org/ws/2/` |
| Rate limit | 1 req/sec |
| Confidence | 0.95+ for fingerprint match; 0.80+ for tag search |

### Discogs (Future Built-in)

| Property | Value |
|----------|-------|
| ID | `discogs` |
| Priority | 20 |
| API | `https://api.discogs.com/` |
| Auth | User token |
| Confidence | 0.85+ for exact match; 0.70+ for search |

### Filename Parser (Built-in)

| Property | Value |
|----------|-------|
| ID | `filename_parser` |
| Priority | 90 |
| Patterns | `{artist} - {album}/{track}. {title}.ext`, scene patterns |
| Confidence | 0.30–0.70 depending on pattern match quality |

## Artwork Providers

| Priority | Provider | Source |
|----------|----------|--------|
| 10 | Cover Art Archive | MusicBrainz release ID |
| 20 | Discogs | Release ID or search |
| 50 | Embedded | Extract from audio file |

```python
@dataclass(frozen=True)
class ArtworkResult:
    source: str
    data: bytes
    mime_type: str
    width: int
    height: int
    confidence: float
    source_id: str | None = None
```

## Media Server Plugins

### Supported Servers

| Plugin ID | Server | API | Direct DB | DB Engine |
|-----------|--------|-----|-----------|-----------|
| `navidrome` | Navidrome | Subsonic | **Yes** | SQLite |
| `jellyfin` | Jellyfin | REST | No | — |
| `plex` | Plex Media Server | Plex API | No | — |
| `emby` | Emby | REST | No | — |
| `ampache` | Ampache | Ampache API | Optional | MySQL |
| `koel` | Koel | REST | Optional | MySQL |
| `subsonic` | Subsonic (generic) | Subsonic API | Depends | varies |
| `funkwhale` | Funkwhale | REST | Optional | PostgreSQL |
| `lyrion` | Lyrion Music Server | CLI/API | Optional | MySQL |
| `mstream` | mStream | REST | No | — |

### MediaServerPlugin Protocol

```python
@dataclass(frozen=True)
class ServerCapabilities:
    direct_db_access: bool = False
    trigger_rescan: bool = True
    validate_metadata: bool = True
    detect_duplicates: bool = False
    get_missing_artwork: bool = True
    get_broken_paths: bool = False

@dataclass(frozen=True)
class ValidationIssue:
    severity: Literal["error", "warning", "info"]
    category: str
    message: str
    server_entity_id: str | None = None
    local_entity_id: UUID | None = None

class MediaServerPlugin(Plugin, Protocol):
    @property
    def capabilities(self) -> ServerCapabilities: ...

    def connect(self, config: MediaServerConfig) -> bool: ...
    def test_connection(self) -> bool: ...
    def disconnect(self) -> None: ...

    # API methods (all servers)
    def trigger_rescan(self) -> bool: ...
    def get_server_stats(self) -> dict[str, Any]: ...

    # Validation (uses DB if available, API fallback)
    def validate_library(self, local_library: LibrarySummary) -> list[ValidationIssue]: ...
    def get_albums_missing_artwork(self) -> list[ServerAlbum]: ...
    def get_duplicate_artists(self) -> list[ServerArtist]: ...
    def get_broken_albums(self) -> list[ServerAlbum]: ...
```

### Navidrome Direct DB Access

Navidrome stores its library in `navidrome.db` (SQLite). The plugin opens a **read-only** connection:

```python
class NavidromePlugin:
    def connect(self, config: NavidromeConfig) -> bool:
        self._api = SubsonicClient(config.url, config.username, config.password)
        if config.db_path:
            uri = f"file:{config.db_path}?mode=ro"
            self._db = sqlite3.connect(uri, uri=True)
        return self._api.ping()

    def get_albums_missing_artwork(self) -> list[ServerAlbum]:
        if self._db:
            return self._query("""
                SELECT a.id, a.name, ar.name as artist
                FROM album a
                JOIN artist ar ON a.artist_id = ar.id
                WHERE a.id NOT IN (
                    SELECT album_id FROM media_file WHERE has_cover_art = 1
                )
            """)
        return self._api.get_albums_without_artwork()  # slower fallback
```

**User must explicitly provide** `db_path` in plugin config. Never auto-detect without consent.

Benefits of direct DB:
- Bulk queries in milliseconds vs. minutes via API
- Access to internal scan status, bookmark data
- Detect server-side issues MusicVault can fix locally

### Subsonic-Compatible Base

Navidrome, Ampache (partially), and generic Subsonic share the Subsonic API. A `SubsonicClient` base class provides common API methods; server-specific plugins extend with DB access where available.

## Plugin Discovery

```toml
[project.entry-points."musicvault.plugins"]
musicbrainz = "musicvault.plugins.builtin.musicbrainz:MusicBrainzPlugin"
discogs = "musicvault.plugins.builtin.discogs:DiscogsPlugin"
cover_art_archive = "musicvault.plugins.builtin.cover_art_archive:CoverArtArchivePlugin"
filename_parser = "musicvault.plugins.builtin.filename_parser:FilenameParserPlugin"
navidrome = "musicvault.plugins.builtin.navidrome:NavidromePlugin"
jellyfin = "musicvault.plugins.builtin.jellyfin:JellyfinPlugin"
plex = "musicvault.plugins.builtin.plex:PlexPlugin"
emby = "musicvault.plugins.builtin.emby:EmbyPlugin"
ampache = "musicvault.plugins.builtin.ampache:AmpachePlugin"
koel = "musicvault.plugins.builtin.koel:KoelPlugin"
subsonic = "musicvault.plugins.builtin.subsonic:SubsonicPlugin"
funkwhale = "musicvault.plugins.builtin.funkwhale:FunkwhalePlugin"
lyrion = "musicvault.plugins.builtin.lyrion:LyrionPlugin"
mstream = "musicvault.plugins.builtin.mstream:MStreamPlugin"
```

Third-party plugins add their own entry points via pip install.

## Plugin Manager

```python
class PluginManager:
    def discover(self) -> list[PluginInfo]: ...
    def load_all(self) -> None: ...

    def get_metadata_providers(self) -> list[MetadataProvider]:
        """Priority-ordered, enabled only."""
        ...

    def get_artwork_providers(self) -> list[ArtworkProvider]: ...
    def get_media_servers(self) -> list[MediaServerPlugin]: ...
    def get_filename_parsers(self) -> list[FilenameParserPlugin]: ...

    def enable(self, plugin_id: str) -> None: ...
    def disable(self, plugin_id: str) -> None: ...
    def set_priority(self, plugin_id: str, priority: int) -> None: ...
    def configure(self, plugin_id: str, config: dict[str, Any]) -> None: ...
```

Failed plugins are disabled with error message visible in Settings → Plugins. Application continues normally.

## Caching

| Cache | Location | TTL |
|-------|----------|-----|
| MusicBrainz | `cache/musicbrainz/` | 7 days |
| Discogs | `cache/discogs/` | 7 days |
| AcoustID | `cache/acoustid/` | 30 days |
| Artwork | `cache/artwork/` | 30 days |
| Server validation | `cache/servers/` | 1 hour |

Cache keys: SHA-256 of `(provider_id, query_params)`.

## Plugin Configuration Schema

Each plugin provides JSON Schema for its settings. Navidrome example:

```json
{
  "type": "object",
  "properties": {
    "url": { "type": "string", "title": "Server URL" },
    "username": { "type": "string", "title": "Username" },
    "password": { "type": "string", "title": "Password", "format": "password" },
    "db_path": {
      "type": "string",
      "title": "Navidrome Database Path (optional)",
      "description": "Path to navidrome.db for direct read access"
    }
  },
  "required": ["url", "username", "password"]
}
```
