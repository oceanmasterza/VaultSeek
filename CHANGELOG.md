# Changelog

All notable changes to MusicVault are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
