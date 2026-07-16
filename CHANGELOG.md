# Changelog

All notable changes to MusicVault are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
  - Downstream artwork/duplicates/rules jobs and `review_items` deferred
    to Phase 7+
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
    the migration boundary into MusicVault's own exception hierarchy
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
  - `src/musicvault/` package skeleton following the v3 folder layout
    (`models/`, `core/`, `db/`, `services/`, `workers/`, `plugins/`, `gui/`)
  - `core/exceptions.py` — application exception hierarchy
  - `core/paths.py` — cross-platform app data directory resolution
    (`%APPDATA%/MusicVault` on Windows)
  - `core/config.py` — versioned JSON configuration with migration chain
  - `core/logging.py` — Loguru sinks (console, `musicvault.log`, `debug.log`, crash logs)
  - `core/event_bus.py` — thread-safe publish/subscribe for domain events
  - `core/container.py` — dependency injection container
  - `app.py` — application bootstrap sequence
  - `__main__.py` — `python -m musicvault` / `musicvault` CLI entry point
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
