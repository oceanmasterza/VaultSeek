# Changelog

All notable changes to VaultSeek are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Acquisition Engine (Phases 4–6)** — end-to-end acquisition pipeline:
  - `LocalSocketRpcClient` + documented NDJSON socket protocol for Nicotine+
  - `HttpApiRpcClient` for [api-nicotine-plus](https://github.com/sjluke/api-nicotine-plus) (port 12339)
  - NDJSON socket companion: `scripts/nicotine_plus_ndjson_proxy.py`
  - `VerificationEngine` — path, tags, SHA-256 / fingerprint duplicate checks
  - `ImportPipeline` — stage into Incoming and enqueue scan (organize/artwork chain)
  - `AcquisitionRunner` — search, score, auto-acquire above threshold, poll downloads
  - `AcquisitionAutomationService` — background auto-acquire, download polling, retry backoff
  - **Acquisition UI** — wishlist page, missing-media scan, result picker, retries column
  - Settings: auto-acquire threshold, Nicotine+ transport (socket/http), API port/token
  - Config schema **v9** (`auto_acquire_threshold`, `transport`, `api_port`, `api_token`)
  - `AcquisitionEngine.schedule_retry()` — atomic retry scheduling

### Fixed

- **Acquisition automation** — jobs in `scoring` no longer re-dispatch provider search every
  poll cycle; retries increment once per failure via atomic `schedule_retry`
- **GUI polling** — removed duplicate download polling from the main-window timer (automation
  service owns polling; acquisition page refreshes display only)
- **Dashboard acquisition summary** — job counts panel and insight when jobs need attention
- **Settings → Test Nicotine+ connection** — probe HTTP or socket transport without saving

### Added

- **Albums cover preview** — selecting an album shows its front cover on the
  right; sidebar order is Artists → Albums → Artwork.
- **Media servers** — Emby, Ampache (Subsonic API), Koel, Funkwhale, and
  Lyrion Music Server rescan plugins (Settings plugin list).
- **Browse UI** — Artists / Albums / Artwork pages (search, track drill-down,
  cover status). Library page adds a zone **folder tree** (Incoming →
  artist/album path segments) with a full-height track table.
- **Force rescan** — Dashboard / File menu re-queues every Incoming audio
  file; normal Scan still skips size/mtime-unchanged files. Scan and
  pipeline jobs store short **completion summaries** (Jobs Details +
  Dashboard processing report).
- **Artwork performance** — prefer good embedded covers before Cover Art
  Archive; reuse album art for sibling tracks; cache MusicBrainz
  release lookups; skip enqueue when album already has a cover; default
  I/O worker threads raised to 3 (config schema v7).
- **Fingerprint sampling** — Settings: fingerprint all files vs sample
  an album folder after N AcoustID confirms (trusted_folders).
- **Incoming leftover cleanup** — after the last audio file leaves an
  Incoming album folder, delete sidecars (`.nfo`, `.sfv`, covers,
  playlists, …) and remove empty folders (Incoming root kept).
- **In-place organize** — files stay in Incoming through identify/rules;
  one move Incoming → Library on auto-approve or Review approve.
- **Album-aware duplicates** — same song on different albums is not a
  duplicate; confident same-album dups can auto keep-best / archive.

### Fixed

- **Duplicate approval left the best track stuck in Staging** — resolving
  a `possible_duplicate` review now also promotes the keeper to Library
  when its review backlog is clear (same gate as other approvals).

### Added

- **Self-contained Windows packaging** — pinned vendor binaries
  (`packaging/vendor_manifest.json` + `fetch_vendor.py`) ship
  **fpcalc** inside the PyInstaller onedir / Inno Setup installer;
  runtime discovers it via `native_bins.configure_native_bin_path`.
  Versioned GitHub release URLs + SHA-256 so dependency links stay
  immutable.

### Fixed

- **Audit hardening (correctness + performance)**:
  - Review approve no longer clears `needs_review` or promotes a staging
    track while other pending items remain for that track
  - `sync_media_server` is coalesced to one pending/running job per
    library (no stampede on bulk library imports)
  - Job dispatcher claims only up to free pool slots (stops marking
    dozens of jobs `running` on a 1-thread meta pool)
  - GUI status poll uses `COUNT` for review badges and no longer
    rebuilds Review/Jobs tables every 2s (preserves selection)
  - Settings loads media-server rows per library/plugin and preserves
    `last_sync_*` on save; preferences update live `container.config`
  - Jobs monitor caps pending/retry/failed lists; `run_gui` always
    runs the Qt event loop before closing the container

### Added

- **Phases 14–16 — GUI, media servers, packaging** (1.0.0-capable):
  - **Phase 14 GUI** — PySide6 main window (sidebar, library selector,
    status bar), Library / Review / Jobs / Duplicates / Rules / Settings
    pages, dark theme, `QtEventBridge`, headless escape for CI
  - **Phase 15 media servers** — `MediaServerPlugin` + Navidrome /
    Jellyfin / Plex / Subsonic; `MediaServerWorker` +
    `sync_media_server` route; organizer enqueues sync on library entry
  - **Phase 16 packaging** — `packaging/vaultseek.spec` (PyInstaller
    onedir), Inno Setup `installer.iss`, packaging README

### Added

- **Phase 13 reports** — library summary exports:
  - `ReportService` builds on-demand aggregates (zone counts, lossless /
    lossy, needs-review, embedded art, pending reviews by type, open
    duplicate groups, quality buckets, average confidence)
  - Built-in **JSON / CSV / HTML** exporters; Excel/PDF deferred
  - `ReportWorker` + dispatcher `generate_report` route; default output
    under `AppPaths.reports_dir`
  - `library_stats` table still deferred (compute-on-demand for now)
  - 487 tests total (up from 477)

### Added

- **Phase 12 rollback engine** — file moves are reversible:
  - `RollbackSnapshot` entity + `OperationRepository` snapshot APIs
    (`record_with_snapshot`, status/restore updates, `list_recent`);
    snapshot payload is gzip-compressed JSON in the existing
    `rollback_snapshots` table
  - `OrganizerWorker` now writes operation + change_history + snapshot
    on every move
  - `OperationOrchestrator` — `preview` / `execute` (enqueue
    `organize_file`) / `rollback` for completed `file_move` ops;
    restores path + zone, skips the forward zone machine for undos,
    suffixes on restore collisions; zone-aware history via
    `list_recent` + `history_for_track`
  - Metadata tag-rewrite rollback deferred (no tag-write path yet)
  - 477 tests total (up from 464)

### Added

- **Phase 11 artwork worker** — album covers enter the pipeline:
  - Artwork tables re-designed from scratch (v1 column spec was lost):
    `artwork` (one row per unique image, deduplicated by SHA-256, bytes
    cached under `cache/artwork/`), `track_artwork` / `album_artwork`
    link tables — Alembic migration `0003` + `ArtworkRepository`
  - `ArtworkProvider` protocol with the documented `ArtworkResult` shape;
    **Cover Art Archive plugin** (priority 10) fetching front covers by
    MusicBrainz release, release-group, or recording id (recording ids
    are resolved to a release via the MusicBrainz API first);
    **embedded-art plugin** (priority 50) extracting FLAC `pictures`,
    ID3 `APIC`, and MP4 `covr` images, preferring front covers
  - `ArtworkWorker` + dispatcher `fetch_artwork` route — first
    priority-ordered result meeting the minimum resolution wins; smaller
    finds are still stored but park an `artwork_low_res` review item;
    nothing found parks `artwork_missing`; `tracks.has_embedded_art` is
    set whenever the file's own tags held a usable picture
  - `MetadataWorker` now enqueues `fetch_artwork` alongside
    `detect_duplicates` — artwork is a side branch that never gates
    organizing
  - Config schema v5: `artwork` section (`fetch_enabled`, `min_width`,
    `min_height`; 500×500 default)
  - 464 tests total (up from 429)

### Added

- **Phase 10 organizer + watch folder** — real file moves close the loop:
  - `OrganizeEngine` (pure domain service) — zone state machine
    (incoming → staging → library, library ↔ archive, plus
    incoming/staging → archive so the archive-MP3 rule stays actionable)
    and destination templating `{Artist}/{Year} - {Album}/{NN} - {Title}{ext}`
    with Windows-safe sanitization
  - `Library` entity + `LibraryRepository`; `Operation`/`ChangeRecord`
    entities + `OperationRepository` — every move writes an
    `operations` + `change_history` audit pair for the Phase 12 rollback
    engine
  - `OrganizerWorker` + dispatcher `organize_file` route — safe move
    (never overwrites, ` (1)` suffix on collision), updates track
    zone/path, auto-approves staging → library when confidence ≥ the
    library threshold with no pending reviews and no open duplicate group
  - `RuleWorker` enqueues `organize_file` → staging for incoming tracks
    (pipeline: scan → hash → fingerprint → identify → duplicates → rules
    → organize)
  - Approval executes moves: `ReviewQueueService.approve` /
    `approve_with_edits` enqueue parked `move_to_zone` rule actions,
    resolve `possible_duplicate` groups as `kept_best` (archiving
    non-best members), and promote approved staging tracks to the library
  - Non-approval `move_to_zone` rule actions enqueue real organize jobs
    (illegal transitions still park a review item)
  - `WatchFolderService` — polling daemon enqueueing priority-50
    `scan_directory` jobs for `watch_enabled` libraries; config schema v4
    adds `watch.poll_interval_seconds` (default 30 s)
  - 429 tests total (up from 374)

### Added

- **Phase 9 duplicate detection** — exact-key duplicate grouping with
  quality ranking:
  - `DuplicateMatcher` (pure domain service) — builds groups from matched
    tracks, best copy via `QualityScorer` (its first production consumer)
  - Match tiers + confidences: content hash (1.0) > Chromaprint
    `fingerprint_hash` (0.95) > `mb_recording_id` (0.90); `fuzzy` deferred
  - `DuplicateGroup` / `DuplicateMember` entities; `DuplicateRepository`
    (save/replace groups, candidate discovery, `has_lossless_duplicate`,
    status/resolution); migration 0002 adds supporting indexes
  - `DuplicateWorker` + dispatcher `detect_duplicates` route; persists
    `tracks.quality_score` for grouped tracks, creates a
    `possible_duplicate` review item linked via `duplicate_group_id`,
    reuses the open group on re-detection
  - Pipeline reordered: identify → `detect_duplicates` → `evaluate_rules`;
    `RuleWorker` now computes the real `has_lossless_duplicate`, so the
    Phase 8 archive-MP3 rule matches (zone move still parked until Phase 10)
  - `ReviewItemCreate.duplicate_group_id` passthrough
  - 374 tests total (up from 355)

### Added

- **Phase 8 rules engine** — user-configurable automation after identify:
  - `RulesEngine` — context build, evaluate/batch, apply matches, default
    seeding, CRUD (create/update/delete/list/enable)
  - `RuleWorker` + dispatcher `evaluate_rules` route (shared metadata I/O pool)
  - `MetadataWorker` enqueues `evaluate_rules` after every identify
  - Shipped defaults: Archive MP3 (Phase 9/10 dependent), Detect VA,
    Flag low bitrate (< 192 kbps → `low_quality` review)
  - Safe actions: `flag_review`, `set_artist`, `set_genre`; `move_to_zone`
    parks a review item until Phase 10
  - `RulesMatchedEvent`; `RuleError`; repo helpers `list_by_library` /
    `find_by_name` / `delete`
  - 355 tests total (up from 346)

### Added

- **Phase 7 review queue** — human approval gate for uncertain metadata:
  - `ReviewQueueService` — create, get_pending, get_by_type, approve,
    reject, defer, approve_with_edits; idempotent pending upsert per
    `(track_id, review_type)`
  - `ReviewItemCreate` DTO + `ReviewItemAddedEvent` on `EventBus`
  - `MetadataWorker` creates `review_items` when `needs_review`
    (artist → album → provider-conflict classification)
  - Approve clears `needs_review` (no zone moves yet — Phase 10)
  - `ReviewRepository` helpers: `find_pending`, `list_by_type`,
    `update_pending_content`
  - Container wiring; GUI review page deferred to Phase 14
  - 346 tests total (up from 333)

### Added

- **Phase 6 metadata arbitrator + providers** — multi-source identification
  with per-field confidence:
  - `MetadataProvider` protocol + query/result types
    (`models/interfaces/metadata.py`)
  - Built-in providers: AcoustID (HTTP), MusicBrainz, local tags (Mutagen),
    filename parser (`plugins/builtin/`)
  - `MetadataArbitrator` — cascade + per-field arbitration;
    `overall_confidence = min(field confidences)`; sets `needs_review`
  - `MetadataConfidenceRepository` + `MetadataWorker` (I/O thread pool)
  - `MetadataConfig` / config schema v2→v3 (provider enablement, order,
    threshold, AcoustID API key, `metadata_worker_threads`)
  - `PluginManager` + `Container` wiring; dispatcher claim-then-dispatch
  - Downstream artwork/duplicates/rules jobs deferred to Phase 8+;
    `review_items` creation delivered in Phase 7
  - 333 tests total (up from 298)

### Added

- **Phase 5 fingerprint worker + Chromaprint persistence** — the next
  pipeline stage after hashing:
  - `FingerprintProvider` / `FingerprintResult`
    (`models/interfaces/fingerprint.py`)
  - Built-in Chromaprint provider (`plugins/builtin/chromaprint/`) via
    `pyacoustid` / `fpcalc`
  - `FingerprintWorker` + `compute_fingerprint` (`workers/cpu/`) —
    ProcessPool Chromaprint generation, persists fingerprint columns on
    `file_identity`, chains to `identify_metadata` (MetadataWorker is
    Phase 6)
  - Shared CPU process pool in `JobDispatcher` for hash + fingerprint
  - Defensive skip when a fingerprint is already stored (crash-recovery
    re-delivery)
  - `HashWorker` now preserves fingerprint fields on unchanged content
    hashes and passes `file_path` into `fingerprint_file` payloads
  - AcoustID HTTP lookup deferred to Phase 6 (metadata identification)
  - 298 tests total (up from 282), 98% coverage overall, 100% on every
    Phase 5 module

### Added

- **Phase 4 job dispatcher + scanner/hash workers** — the first live, running
  background pipeline, built and verified in 7 small increments:
  - `PipelineConfig` (`core/config.py`, schema v1→v2 migration) — batch size,
    flush interval, worker pool size, and retry backoff tunables
  - `WriteDTO` + `DatabaseWriter` (`db/writer.py`) — single-writer background
    thread that batches worker-submitted rows into large transactions,
    logging (not crashing) on a bad batch
  - `JobRepository.claim_pending`/`recover_orphaned`/`promote_due_retries`/
    `reset_for_retry` — atomic job-state transitions plus the aggregation
    queries behind `JobStatsDTO`
  - `JobQueueService` (`services/job_queue_service.py`) —
    enqueue/claim/complete/fail (exponential backoff)/cancel/retry/recover/
    stats orchestration over `JobRepository`
  - `ScannerWorker` (`workers/io/`, `ThreadPoolExecutor`) — walks a directory,
    upserts `Track` rows via `DatabaseWriter`, enqueues `hash_file` per audio
    file, preserving existing metadata on rescan via `dataclasses.replace`
  - `HashWorker` + `compute_hash` (`workers/cpu/`, `ProcessPoolExecutor`) — a
    pure, picklable hash function plus result handling that only chains to
    `fingerprint_file` when the content hash actually changed
  - `JobDispatcher` (`services/job_dispatcher.py`) — polls the queue,
    dispatches to the two worker pools, exposes `recover()` for startup
    crash recovery
  - Wired into `Container.bootstrap`: the database writer and dispatcher now
    start automatically on every application startup, after
    `dispatcher.recover()` resets any job an earlier crash left `running`
    back to `retry`
  - 282 tests total (up from 213), 99% coverage overall, 100% on every
    Phase 4 module

### Added

- **Phase 3 domain models** — the richer domain layer deferred from Phase 2:
  - `Track`, `Album`, `Artist` entities (`models/entities/`) + `LibraryZone`
    enum, matching the `tracks`/`albums`/`artists` tables column-for-column
  - `TrackRepository`, `AlbumRepository`, `ArtistRepository`
    (`db/repositories/`) — `TrackRepository`'s methods (`get_by_id`,
    `get_by_path`, `get_by_library`, `upsert_batch`, `update_zone`) follow
    the protocol documented in `04-service-layer.md` exactly
  - `QualityScorer` + `QualityWeights` (`models/services/`) — reproduces the
    documented example scores exactly (FLAC 24-bit → 100, FLAC 16-bit → 95,
    MP3 320 → 70), with additional named, overridable brackets for common
    MP3/AAC bitrates
  - `RenameEngine.clean_filename` (`models/services/`) — strips
    scene-release tag blocks (`-(KR147)-...`, `-[AFO]-...`) from filenames,
    matching the 3 documented examples exactly
  - Rules AST — `RuleNode`/`ConditionLeaf`/`AndNode`/`OrNode` +
    `parse_conditions` (`models/value_objects/rule_condition.py`),
    implementing the AST evaluation approach from `12-pipeline-engine-v3.md`
  - `RuleAction`, `FieldConfidence` value objects (`models/value_objects/`)
  - All five Phase 3 repositories wired into `Container.bootstrap`
  - `DuplicateMatcher` and `OrganizeEngine` deliberately deferred to Phases
    9 and 10, where the docs actually specify their behavior (see
    `07-roadmap.md`, Phase 3 scope decisions)
  - 213 tests total (up from 127), 99% coverage overall, 100% on every
    domain service module

### Fixed

- **Corrected a YAML example inconsistency** in `12-pipeline-engine-v3.md`
  ("Rules Engine — AST Evaluation"): it used `op`/`type`/`params` as key
  names, which didn't match the actual `RuleCondition`/`RuleAction`
  dataclass fields (`operator`/`action_type`/`parameters`) documented in
  `10-revision-v2.md`. Caught while implementing the rules AST in Phase 3.

### Added

- **Phase 2 database layer** — SQLAlchemy Core, UUIDv7, Alembic migrations, and the
  first four repositories:
  - `db/tables.py` — all 15 fully-specified v2 tables as SQLAlchemy Core `Table`
    objects (5 additional tables — `artwork`, `track_artwork`, `album_artwork`,
    `plugin_state`, `library_stats` — are deferred to the phases that actually need
    them; their schemas were never fully documented, see `07-roadmap.md`)
  - `db/uuid_utils.py` — `uuid7()` generation + `uuid_to_blob`/`blob_to_uuid`
    conversion for `BLOB(16)` primary keys
  - `db/engine.py` — SQLite engine factory applying WAL mode, foreign keys,
    busy timeout, and adaptive `mmap_size` (25% of available RAM, floored at
    256 MB, capped at 30 GB) on every pooled connection
  - Alembic migrations (`db/migrations/`) with a programmatic `run_migrations`/
    `downgrade_migrations` runner, `black`/`ruff` post-write hooks, and the
    `0001_initial_schema` migration
  - `db/repositories/base.py` — generic `batch_upsert` (SQLite
    `INSERT ... ON CONFLICT DO UPDATE`), proven against 500 `jobs` rows in
    under a second
  - `JobRepository`, `ReviewRepository`, `RuleRepository`, `FileIdentityRepository`,
    with minimal entities/value objects (`Job`, `ReviewItem`, `Rule`,
    `FileIdentity`) pulled forward from Phase 3 as their return types
  - `core/exceptions.DatabaseError` — translates Alembic/SQLAlchemy failures at
    the migration boundary into VaultSeek's own exception hierarchy
  - `Container.bootstrap` now runs migrations and opens the database on every
    application startup (satisfying "DB auto-created on first run"), and
    `Container.close()` disposes the engine on shutdown
  - 127 tests total (up from 43), 98% coverage

### Fixed

- **Corrected minimum Python version from 3.13 to 3.14** across `pyproject.toml`, both
  CI workflows, and all architecture docs. The original architecture notes incorrectly
  claimed `uuid.uuid7()` was added to the standard library in Python 3.12; verified
  against the official CPython changelog that it was actually added in **3.14**.
  Since UUIDv7 generation is used for every primary key in the entire database schema
  (Phase 2), this was caught and fixed *before* writing any database code, rather than
  after a confusing CI-only failure (local dev already had 3.14 installed, so the bug
  would not have reproduced locally). Also fixed a related inconsistency in
  `03-database-schema.md` where a few tables (`file_identity`, `duplicate_members`,
  `media_server_state`) still showed `TEXT` UUID columns instead of `BLOB(16)`.

### Added

- **Phase 1 project scaffold** — first runnable application code:
  - `src/vaultseek/` package skeleton following the v3 folder layout
    (`models/`, `core/`, `db/`, `services/`, `workers/`, `plugins/`, `gui/`)
  - `core/exceptions.py` — application exception hierarchy
  - `core/paths.py` — cross-platform app data directory resolution
    (`%APPDATA%/VaultSeek` on Windows)
  - `core/config.py` — versioned JSON configuration with migration chain
  - `core/logging.py` — Loguru sinks (console, `vaultseek.log`, `debug.log`, crash logs)
  - `core/event_bus.py` — thread-safe publish/subscribe for domain events
  - `core/container.py` — dependency injection container
  - `app.py` — application bootstrap sequence
  - `__main__.py` — `python -m vaultseek` / `vaultseek` CLI entry point
  - `config/defaults.json` — default configuration template
  - 43 tests (unit + integration), 97% coverage
  - `pyproject.toml` with full dependency set and tool configuration
    (ruff, black, mypy strict, import-linter, pytest)
  - `.github/workflows/ci.yml` — lint, typecheck, and test on every push/PR
  - `.github/workflows/release.yml` — PyInstaller build on version tags
  - `CONTRIBUTING.md` — development setup and contribution guidelines
- Architecture v3 pipeline engine refinements ([12-pipeline-engine-v3.md](docs/architecture/12-pipeline-engine-v3.md)):
  - Dedicated single-writer DB queue (eliminates SQLite lock contention)
  - ProcessPool for CPU-bound workers (hash, fingerprint, audio parse)
  - ThreadPool for I/O-bound workers (scan, HTTP, file ops)
  - Event bus + Qt bridge for GUI decoupling
  - UUID v7 stored as BLOB(16) instead of TEXT(36)
  - Batch writes increased to 5,000–10,000 rows
  - Adaptive mmap sizing (not fixed 30 GB)
  - Dual metadata cascades (identification vs enrichment)
  - Composite confidence scoring formula
  - Rules engine AST evaluation spec
  - Folder layout renamed: models/, services/, db/, workers/
- Updated performance strategy and folder layout for v3

### Changed

- Navidrome integration explicitly read-only for DB (writes via API only)
- UUID v4 recommendation evaluated; v7 retained for index locality

### Added (v2)
  - Scalability risk review (10 risks identified and mitigated)
  - SQLAlchemy Core instead of ORM
  - UUID v7 primary keys for all entities
  - Persistent job queue with independent workers
  - Metadata arbitration with per-field confidence scoring
  - Review queue for uncertain matches (< 90% threshold)
  - Staging library (Incoming → Staging → Review → Library)
  - User-configurable rules engine
  - Watch folder with zero-click automation pipeline
  - Fingerprint/hash persistence with skip-if-unchanged logic
  - Visual duplicate viewer design
  - 10 media server plugins (Navidrome with direct DB access)
  - CI pipeline specification (GitHub Actions from Phase 1)
- Updated all architecture documents (01–07) for v2 consistency
- New documents: 10-revision-v2.md, 11-ci-pipeline.md

### Changed

- Database schema: integer IDs → UUID v7; added jobs, review_items, rules, file_identity tables
- Service layer: monolithic services → job queue + worker architecture
- Plugin API: expanded from 4 to 10 media servers; metadata providers return confidence scores
- GUI: added Review Queue, Job Monitor, Rules Editor, Duplicate Viewer pages
- Roadmap: 14 phases → 16 phases; CI moved from Phase 14 to Phase 1
- Target users: expanded media server list (Jellyfin, Plex, Emby, Ampache, Koel, etc.)

## [0.0.0] - 2026-07-15

### Added

- Project inception — architecture phase only, no application code
