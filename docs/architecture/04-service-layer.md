# 04 — Service Layer (v2)

> **Revision**: v2 — Job queue replaces direct service chains. See [10-revision-v2.md](10-revision-v2.md).

## Overview

The application layer orchestrates use cases through a **persistent job queue** and **worker pools**. Services are stateless; all state lives in SQLite. Workers are invoked by `JobDispatcher`, not by each other directly.

## Architecture Shift: v1 → v2

| v1 | v2 |
|----|-----|
| `ScannerService.scan_library()` calls everything | Scanner enqueues jobs; workers process independently |
| `MetadataService` calls MusicBrainz | `MetadataArbitrator` ranks all providers |
| Auto-apply metadata | Review queue for confidence < 90% |
| Direct organize to library | Organize to staging; approve → library |
| Integer track IDs | UUID v7 everywhere |

## Application Services

| Service | Responsibility |
|---------|---------------|
| `JobQueueService` | Enqueue, claim, complete, fail, retry jobs |
| `JobDispatcher` | Poll queue, dispatch to worker pools, crash recovery |
| `MetadataArbitrator` | Multi-provider metadata with per-field confidence |
| `ReviewQueueService` | Manage review items (create, approve, reject, defer) |
| `RulesEngine` | Evaluate user rules against tracks |
| `WatchFolderService` | Monitor incoming folder, enqueue scan jobs |
| `OperationOrchestrator` | Safety gate: dry-run, snapshot, execute, rollback |
| `ReportService` | Generate HTML/CSV/Excel/PDF reports |

## Workers (Job Handlers)

Workers are **not** services — they are stateless job executors registered with the dispatcher:

| Worker | Job Type | Enqueues |
|--------|----------|----------|
| `ScannerWorker` | `scan_directory` | `hash_file` per file |
| `HashWorker` | `hash_file` | `fingerprint_file` if identity changed |
| `FingerprintWorker` | `fingerprint_file` | `identify_metadata` |
| `MetadataWorker` | `identify_metadata` | `fetch_artwork`, `detect_duplicates`, `evaluate_rules` |
| `ArtworkWorker` | `fetch_artwork` | (terminal or review) |
| `DuplicateWorker` | `detect_duplicates` | review item if match found |
| `RuleWorker` | `evaluate_rules` | `organize_file` or review item |
| `OrganizerWorker` | `organize_file` | `sync_media_server` |
| `MediaServerWorker` | `sync_media_server` | (terminal) |
| `ReportWorker` | `generate_report` | (terminal) |

## JobQueueService

```python
class JobQueueService:
    def __init__(self, job_repository: JobRepository) -> None: ...

    def enqueue(
        self,
        job_type: JobType,
        library_id: UUID,
        payload: dict[str, Any],
        *,
        priority: int = 100,
        parent_job_id: UUID | None = None,
    ) -> UUID: ...

    def enqueue_batch(self, jobs: Sequence[JobCreate]) -> list[UUID]: ...

    def claim_pending(self, job_type: JobType, limit: int = 10) -> Sequence[Job]: ...

    def mark_running(self, job_id: UUID) -> None: ...
    def mark_completed(self, job_id: UUID) -> None: ...
    def mark_failed(self, job_id: UUID, error: str) -> None: ...

    def get_stats(self, library_id: UUID) -> JobStats: ...
    def cancel(self, job_id: UUID) -> None: ...
    def retry_failed(self, job_id: UUID) -> None: ...

    def recover_orphaned(self) -> int:
        """Reset running→retry on startup. Returns count recovered."""
        ...
```

## MetadataArbitrator

```python
@dataclass(frozen=True)
class FieldConfidence:
    field: str
    value: str | int | None
    confidence: float
    source: str

@dataclass(frozen=True)
class ArbitrationResult:
    track_id: UUID
    fields: dict[str, FieldConfidence]
    overall_confidence: float
    needs_review: bool

class MetadataArbitrator:
    def __init__(
        self,
        plugin_manager: PluginManager,
        confidence_threshold: float = 0.90,
    ) -> None: ...

    def resolve(self, track: Track, fingerprint: FingerprintData | None) -> ArbitrationResult:
        """Query all providers, arbitrate per-field, return result."""
        ...

    def _query_providers(self, track: Track, fp: FingerprintData | None) -> list[ProviderResult]: ...
    def _arbitrate_fields(self, results: list[ProviderResult]) -> dict[str, FieldConfidence]: ...
```

Provider priority (configurable):

1. MusicBrainz (fingerprint, tags, MBID)
2. Discogs
3. Local embedded tags
4. Filename parser

Artwork uses separate chain: Cover Art Archive → Discogs → embedded.

## ReviewQueueService

```python
class ReviewQueueService:
    def create_item(self, item: ReviewItemCreate) -> UUID: ...

    def get_pending(self, library_id: UUID) -> Sequence[ReviewItem]: ...
    def get_by_type(self, library_id: UUID, review_type: ReviewType) -> Sequence[ReviewItem]: ...

    def approve(self, item_id: UUID) -> None:
        """Apply metadata, move staging→library if applicable."""
        ...

    def reject(self, item_id: UUID, reason: str | None = None) -> None: ...
    def defer(self, item_id: UUID) -> None: ...

    def approve_with_edits(self, item_id: UUID, edits: dict[str, Any]) -> None: ...
```

## RulesEngine

```python
class RulesEngine:
    def __init__(self, rule_repository: RuleRepository) -> None: ...

    def evaluate(self, track: Track, context: RuleContext) -> list[RuleMatch]: ...
    def evaluate_batch(self, track_ids: Sequence[UUID]) -> dict[UUID, list[RuleMatch]]: ...

@dataclass(frozen=True)
class RuleMatch:
    rule_id: UUID
    rule_name: str
    actions: list[RuleAction]
    requires_approval: bool
```

`RuleContext` includes: track metadata, quality score, duplicate status, zone, codec, bitrate, `has_lossless_duplicate` flag.

## WatchFolderService

```python
class WatchFolderService:
    def __init__(
        self,
        job_queue: JobQueueService,
        config: WatchFolderConfig,
    ) -> None: ...

    def start(self, library_id: UUID) -> None:
        """Begin monitoring incoming_path using ReadDirectoryChangesW."""
        ...

    def stop(self) -> None: ...

    def _on_file_created(self, path: Path) -> None:
        self._job_queue.enqueue(
            JobType.SCAN_DIRECTORY,
            library_id=self._library_id,
            payload={"path": str(path), "source": "watch_folder"},
            priority=50,  # Higher priority than bulk scans
        )
```

## OperationOrchestrator

Unchanged in responsibility, updated for zones and UUIDs:

```python
class OperationOrchestrator:
    def preview(self, request: OperationRequest) -> OperationResult: ...
    def execute(self, request: OperationRequest) -> OperationResult: ...
    def rollback(self, operation_id: UUID) -> OperationResult: ...
```

All mutating operations:
1. Create rollback snapshot
2. Record `change_history` including `old_zone` / `new_zone`
3. Never move files from staging → library without explicit approval

## Repository Protocols (UUID-based)

```python
class TrackRepository(Protocol):
    def get_by_id(self, track_id: UUID) -> Track | None: ...
    def get_by_path(self, file_path: str) -> Track | None: ...
    def get_by_library(
        self, library_id: UUID, zone: LibraryZone | None = None,
        *, offset: int = 0, limit: int = 100,
    ) -> Sequence[Track]: ...
    def upsert_batch(self, tracks: Sequence[Track]) -> int: ...
    def update_zone(self, track_id: UUID, zone: LibraryZone) -> None: ...
```

All repositories use **SQLAlchemy Core** — no ORM session, no identity map.

## DTOs

```python
@dataclass(frozen=True)
class TrackSummaryDTO:
    id: UUID
    title: str
    artist_name: str
    album_title: str
    zone: LibraryZone
    file_path: str
    quality_score: int | None
    overall_confidence: float | None
    needs_review: bool

@dataclass(frozen=True)
class JobStatsDTO:
    pending: int
    running: int
    failed: int
    completed_today: int
    by_type: dict[str, int]

@dataclass(frozen=True)
class ReviewItemDTO:
    id: UUID
    review_type: ReviewType
    title: str
    confidence: float | None
    track: TrackSummaryDTO | None
    duplicate_group: DuplicateGroupDTO | None
    created_at: datetime
```

## Event Flow: GUI ↔ Job Queue

ViewModels never call workers directly:

```
User clicks "Scan Library"
  → LibraryViewModel.start_scan()
    → JobQueueService.enqueue(SCAN_DIRECTORY, ...)
    → JobMonitorViewModel polls JobQueueService.get_stats()

JobDispatcher (background thread)
  → claims jobs → executes workers → updates status

Worker completes
  → JobQueueService.mark_completed()
  → (optional) notify GUI via callback/signal

Review item created
  → ReviewQueueService.create_item()
  → ReviewViewModel refresh on next poll
```

## Error Handling

| Failure | Worker Behavior |
|---------|----------------|
| Corrupt file | Mark job completed with warning; create review item |
| API rate limit | Mark job retry with 60s delay |
| API timeout | Retry up to max_attempts |
| DB locked | Retry with 1s backoff |
| Unknown error | Mark failed; user can retry from Job Monitor |

Workers never raise unhandled exceptions — all caught, logged, recorded in `jobs.error_message`.
