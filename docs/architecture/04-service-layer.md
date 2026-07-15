# 04 — Service Layer

## Overview

The service layer (`application/`) orchestrates use cases by coordinating domain logic, repositories, and plugins. Services are **stateless** — all persistent state lives in the database.

## Service Catalog

| Service | Responsibility | Dependencies |
|---------|---------------|--------------|
| `ScannerService` | Discover and ingest audio files | `FileWalker`, `AudioFileReader`, `FingerprintGenerator`, `TrackRepository`, `ScanRepository` |
| `FingerprintService` | Generate and lookup fingerprints | `FingerprintGenerator`, `AcoustIDClient`, `FingerprintRepository` |
| `MetadataService` | Identify and fix metadata | `PluginManager`, `TrackRepository`, `AlbumRepository`, `ArtistRepository` |
| `DuplicateService` | Detect and manage duplicates | `DuplicateMatcher`, `QualityScorer`, `DuplicateRepository` |
| `OrganizerService` | Move files to target folder structure | `OrganizeEngine`, `FileOperations`, `TrackRepository` |
| `RenameService` | Clean filenames and paths | `RenameEngine`, `FileOperations`, `TrackRepository` |
| `ArtworkService` | Detect, download, embed artwork | `PluginManager`, `ArtworkProcessor`, `ArtworkRepository` |
| `RollbackService` | Snapshot and restore operations | `RollbackRepository`, `ChangeHistoryRepository`, `FileOperations` |
| `ReportService` | Generate HTML/CSV/Excel/PDF reports | Various repositories, template engine |
| `OperationOrchestrator` | Gate all mutating operations | `RollbackService`, all mutating services |

## Interface Definitions (Protocols)

All interfaces live in `domain/interfaces/`. Services depend on protocols, not implementations.

### Repository Protocols

```python
from typing import Protocol, Sequence
from musicvault.domain.entities.track import Track

class TrackRepository(Protocol):
    def get_by_id(self, track_id: int) -> Track | None: ...
    def get_by_path(self, file_path: str) -> Track | None: ...
    def get_by_library(self, library_id: int, *, offset: int = 0, limit: int = 100) -> Sequence[Track]: ...
    def get_unknown(self, library_id: int) -> Sequence[Track]: ...
    def upsert(self, track: Track) -> Track: ...
    def upsert_batch(self, tracks: Sequence[Track]) -> int: ...
    def delete(self, track_id: int) -> None: ...
    def count_by_library(self, library_id: int) -> int: ...
    def update_quality_scores(self, scores: dict[int, int]) -> None: ...
```

```python
class AlbumRepository(Protocol):
    def get_by_id(self, album_id: int) -> Album | None: ...
    def get_by_mbid(self, mbid: str) -> Album | None: ...
    def get_by_artist(self, artist_id: int) -> Sequence[Album]: ...
    def upsert(self, album: Album) -> Album: ...
    def get_missing_artwork(self, library_id: int) -> Sequence[Album]: ...
```

```python
class ScanRepository(Protocol):
    def create_session(self, library_id: int, scan_type: str) -> ScanSession: ...
    def update_progress(self, session_id: int, **stats) -> None: ...
    def complete_session(self, session_id: int, status: str) -> None: ...
    def get_latest(self, library_id: int) -> ScanSession | None: ...
    def get_history(self, library_id: int, limit: int = 20) -> Sequence[ScanSession]: ...
```

```python
class DuplicateRepository(Protocol):
    def save_group(self, group: DuplicateGroup) -> DuplicateGroup: ...
    def get_unresolved(self, library_id: int) -> Sequence[DuplicateGroup]: ...
    def mark_resolved(self, group_id: int, resolution: str) -> None: ...
    def clear_library(self, library_id: int) -> None: ...
```

```python
class RollbackRepository(Protocol):
    def create_snapshot(self, operation_id: int, data: bytes) -> int: ...
    def get_snapshot(self, snapshot_id: int) -> bytes | None: ...
    def mark_restored(self, snapshot_id: int) -> None: ...
```

### Infrastructure Protocols

```python
class AudioFileReader(Protocol):
    SUPPORTED_EXTENSIONS: frozenset[str]

    def read_metadata(self, file_path: str) -> AudioMetadata: ...
    def read_artwork(self, file_path: str) -> bytes | None: ...
    def can_read(self, file_path: str) -> bool: ...
```

```python
class FingerprintGenerator(Protocol):
    def generate(self, file_path: str) -> FingerprintResult: ...
    def is_available(self) -> bool: ...
```

```python
class FileOperations(Protocol):
    def move(self, src: str, dst: str) -> None: ...
    def rename(self, src: str, dst: str) -> None: ...
    def safe_delete(self, path: str) -> None: ...
    def exists(self, path: str) -> bool: ...
    def ensure_directory(self, path: str) -> None: ...
```

## Service Implementations

### ScannerService

```python
@dataclass
class ScanOptions:
    scan_type: Literal["full", "incremental"] = "incremental"
    generate_fingerprints: bool = True
    compute_hashes: bool = True
    max_workers: int = 8

@dataclass
class ScanProgress:
    session_id: int
    files_processed: int
    files_total: int
    files_added: int
    files_updated: int
    files_errored: int
    current_file: str

class ScannerService:
    def __init__(
        self,
        file_walker: FileWalker,
        audio_reader: AudioFileReader,
        fingerprint_gen: FingerprintGenerator,
        hash_calculator: HashCalculator,
        track_repo: TrackRepository,
        scan_repo: ScanRepository,
        quality_scorer: QualityScorer,
    ) -> None: ...

    def scan_library(
        self,
        library_id: int,
        options: ScanOptions,
        progress_callback: Callable[[ScanProgress], None] | None = None,
    ) -> ScanSession: ...

    def cancel_scan(self, session_id: int) -> None: ...
```

**Incremental scan logic**:
1. Walk filesystem, collect all audio file paths + mtimes
2. Compare against `tracks.file_path` + `tracks.file_modified` in DB
3. Only process files that are new or modified
4. Mark tracks whose files no longer exist as `removed`

### MetadataService

```python
@dataclass
class MetadataMatch:
    track_id: int
    mb_recording_id: str | None
    mb_release_id: str | None
    artist: str
    album: str
    title: str
    track_number: int | None
    disc_number: int | None
    year: int | None
    genre: str | None
    composer: str | None
    confidence: float

@dataclass
class MetadataFixResult:
    track_id: int
    fields_changed: dict[str, tuple[str | None, str | None]]
    match_source: str

class MetadataService:
    def __init__(
        self,
        plugin_manager: PluginManager,
        track_repo: TrackRepository,
        album_repo: AlbumRepository,
        artist_repo: ArtistRepository,
    ) -> None: ...

    def identify_track(self, track_id: int) -> MetadataMatch | None: ...
    def identify_batch(self, track_ids: Sequence[int]) -> list[MetadataMatch]: ...
    def apply_match(self, match: MetadataMatch) -> MetadataFixResult: ...
    def apply_matches(self, matches: Sequence[MetadataMatch]) -> list[MetadataFixResult]: ...
```

**Identification priority**:
1. AcoustID fingerprint lookup → MusicBrainz recording
2. Existing MusicBrainz IDs in tags
3. Fuzzy tag match (artist + title + duration) via RapidFuzz
4. Mark as `is_unknown = TRUE` if all fail

### DuplicateService

```python
@dataclass
class DuplicateDetectionOptions:
    use_fingerprints: bool = True
    use_mbids: bool = True
    use_hashes: bool = True
    use_fuzzy: bool = True
    min_confidence: float = 0.85

@dataclass
class DuplicateReport:
    groups_found: int
    total_duplicates: int
    potential_savings_bytes: int
    groups: Sequence[DuplicateGroup]

class DuplicateService:
    def __init__(
        self,
        duplicate_matcher: DuplicateMatcher,
        quality_scorer: QualityScorer,
        duplicate_repo: DuplicateRepository,
        track_repo: TrackRepository,
    ) -> None: ...

    def detect_duplicates(
        self,
        library_id: int,
        options: DuplicateDetectionOptions,
    ) -> DuplicateReport: ...

    def resolve_group(
        self,
        group_id: int,
        action: Literal["keep_best", "keep_all", "ignore"],
    ) -> None: ...
```

**Detection algorithm**:
1. **Exact hash match** — `content_sha256` identical → confidence 1.0
2. **MusicBrainz recording ID** — same `mb_recording_id` → confidence 0.99
3. **AcoustID match** — same `acoustid_id` → confidence 0.95
4. **Fuzzy match** — similar fingerprint + duration within 2s → confidence 0.85–0.94
5. Within each group, `QualityScorer` ranks tracks; highest wins

### QualityScorer (Domain Service)

```python
@dataclass(frozen=True)
class QualityWeights:
    """Configurable quality scoring weights."""
    flac_24bit: int = 100
    flac_16bit: int = 95
    ape: int = 92
    alac: int = 90
    wav: int = 88
    aiff: int = 88
    dsd: int = 98
    lossless_base: int = 85
    mp3_320: int = 70
    mp3_256: int = 60
    mp3_192: int = 50
    mp3_128: int = 35
    mp3_below_128: int = 20
    aac_256: int = 55
    opus_128: int = 55

class QualityScorer:
    def __init__(self, weights: QualityWeights) -> None: ...

    def score(self, track: Track) -> int: ...
    def rank(self, tracks: Sequence[Track]) -> list[Track]: ...
    def best(self, tracks: Sequence[Track]) -> Track: ...
```

### OrganizerService

```python
@dataclass
class OrganizeRule:
    name: str
    priority: int
    conditions: OrganizeConditions   # codec, genre, is_compilation, etc.
    path_template: str               # "{format}/{artist}/{year} - {album}"

class OrganizerService:
    def __init__(
        self,
        organize_engine: OrganizeEngine,
        file_ops: FileOperations,
        track_repo: TrackRepository,
    ) -> None: ...

    def preview(self, track_ids: Sequence[int], rules: Sequence[OrganizeRule]) -> list[OrganizePreview]: ...
    def organize(self, track_ids: Sequence[int], rules: Sequence[OrganizeRule]) -> OrganizeResult: ...
```

### RenameService

```python
class RenameService:
    def __init__(
        self,
        rename_engine: RenameEngine,
        file_ops: FileOperations,
        track_repo: TrackRepository,
    ) -> None: ...

    def preview(self, track_ids: Sequence[int]) -> list[RenamePreview]: ...
    def rename(self, track_ids: Sequence[int]) -> RenameResult: ...
```

**RenameEngine** strips scene patterns:
- Release group tags: `-SINGLE-`, `-WEB-`, `-FLAC-`, `-16BIT-`, `-24BIT-`
- Scene prefixes: `[AFO]`, `[OBZEN]`, `[FMC]`, `[SCENE]`
- Release IDs: `(KR147)`, `[WEB]`
- Replaces underscores with spaces, normalizes whitespace

### RollbackService

```python
class RollbackService:
    def __init__(
        self,
        rollback_repo: RollbackRepository,
        change_history_repo: ChangeHistoryRepository,
        file_ops: FileOperations,
        track_repo: TrackRepository,
    ) -> None: ...

    def create_snapshot(self, operation_id: int, track_ids: Sequence[int]) -> int: ...
    def rollback(self, operation_id: int) -> RollbackResult: ...
    def can_rollback(self, operation_id: int) -> bool: ...
    def list_operations(self, limit: int = 50) -> Sequence[Operation]: ...
```

**Snapshot contents** (compressed JSON):
```json
{
  "tracks": [
    {
      "id": 42,
      "file_path": "D:/Music/original/path.flac",
      "metadata": { "title": "...", "artist": "...", ... },
      "artwork_bytes_base64": "..."
    }
  ]
}
```

### OperationOrchestrator

Central gate ensuring safety for all mutating operations.

```python
@dataclass
class OperationRequest:
    operation_type: str
    track_ids: Sequence[int]
    options: dict[str, Any]
    dry_run: bool = True

@dataclass
class OperationResult:
    operation_id: int
    status: str
    changes: Sequence[ChangeRecord]
    errors: Sequence[str]

class OperationOrchestrator:
    def __init__(
        self,
        rollback_service: RollbackService,
        metadata_service: MetadataService,
        rename_service: RenameService,
        organizer_service: OrganizerService,
        artwork_service: ArtworkService,
        duplicate_service: DuplicateService,
    ) -> None: ...

    def preview(self, request: OperationRequest) -> OperationResult: ...
    def execute(self, request: OperationRequest) -> OperationResult: ...
    def rollback(self, operation_id: int) -> OperationResult: ...
```

**Workflow**:
```
preview(dry_run=True)  →  user reviews  →  execute(dry_run=False)
                                              ↓
                                        create_snapshot()
                                              ↓
                                        apply_changes()
                                              ↓
                                        record_change_history()
```

## Event / Progress Callbacks

Services do not use Qt signals directly. Instead, they accept optional callback functions:

```python
ProgressCallback = Callable[[ScanProgress], None]
```

The GUI layer wraps these in `QRunnable` workers that emit Qt signals:

```python
class ScanWorker(QRunnable):
    def run(self) -> None:
        self._service.scan_library(
            library_id=self._library_id,
            options=self._options,
            progress_callback=self._emit_progress,
        )
```

This keeps the application layer free of Qt dependencies.

## Error Handling in Services

Services catch infrastructure exceptions and wrap them in domain exceptions:

```python
# domain/exceptions.py hierarchy
class MusicVaultError(Exception): ...
class ScanError(MusicVaultError): ...
class CorruptFileError(ScanError): ...
class MetadataLookupError(MusicVaultError): ...
class OperationError(MusicVaultError): ...
class RollbackError(MusicVaultError): ...
```

Services never let raw exceptions propagate to the GUI. The `OperationOrchestrator` collects errors per-track and returns them in `OperationResult.errors`.

## DTOs (Data Transfer Objects)

DTOs in `application/dto/` are immutable dataclasses for GUI consumption. They are deliberately simpler than domain entities:

```python
@dataclass(frozen=True)
class TrackSummaryDTO:
    id: int
    title: str
    artist_name: str
    album_title: str
    file_path: str
    duration_ms: int | None
    codec: str | None
    quality_score: int | None
    has_artwork: bool
    is_unknown: bool
```

Mapping from entities to DTOs happens in the service layer or a dedicated `DtoMapper`.

## Service Lifecycle

| Phase | Action |
|-------|--------|
| App startup | Container creates all service singletons |
| Plugin load | `PluginManager` registers providers; services receive updated manager |
| Scan | `ScannerService` created per-request with thread pool |
| Shutdown | Services flushed; DB connections closed |

Services are **not** recreated per operation. The DI container manages their lifetime.
