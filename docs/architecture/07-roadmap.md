# 07 — Development Roadmap (v2)

> **Revision**: v2 — Realigned phases for job queue, review, rules, staging. CI from Phase 1.
> See [10-revision-v2.md](10-revision-v2.md).

## Principles

1. Each phase compiles, runs, and passes CI before the next begins
2. Git commit after every milestone
3. CHANGELOG updated with each phase
4. **CI gates every commit from Phase 1** (ruff, black, mypy, pytest)
5. No application code until Phase 0b (this revision) is committed

## Phase Overview

```
Phase 0   ██████████ Architecture v1
Phase 0b  ██████████ Architecture v2 revision
Phase 1   ██████████ Scaffold + CI
Phase 2   ██████████ Database (Core + UUID + jobs)
Phase 3   ██████████ Domain models + repositories
Phase 4   ██████████ Job dispatcher + scanner/hash workers
Phase 5   ██████████ Fingerprint worker + persistence
Phase 6   ██████████ Metadata arbitrator + providers
Phase 7   ██████████ Review queue + confidence scoring
Phase 8   ░░░░░░░░░░ Rules engine (CURRENT)
Phase 9   ░░░░░░░░░░ Duplicate worker + quality scoring
Phase 10  ░░░░░░░░░░ Organizer + staging zones + watch folder
Phase 11  ░░░░░░░░░░ Artwork worker
Phase 12  ░░░░░░░░░░ Rollback engine
Phase 13  ░░░░░░░░░░ Reports
Phase 14  ░░░░░░░░░░ GUI (all pages)
Phase 15  ░░░░░░░░░░ Media server plugins
Phase 16  ░░░░░░░░░░ Packaging + installer
```

---

## Phase 0b: Architecture Revision v2

**Status**: In progress

### Deliverables
- [x] Scalability risk review (10 critical/high risks identified)
- [x] Revised architecture document (10-revision-v2.md)
- [x] Updated database schema (UUID, jobs, review, staging, file_identity)
- [x] Updated service layer (job queue, arbitrator, rules engine)
- [x] Updated plugin API (10 media servers, metadata ranking)
- [x] Updated GUI architecture (review, jobs, duplicates, rules)
- [x] CI pipeline specification (11-ci-pipeline.md)
- [ ] Git commit

### Acceptance Criteria
- All v2 documents internally consistent
- v1 conflicts explicitly superseded
- Phase 1 scope clearly defined and bounded

---

## Phase 1: Project Scaffold + CI

**Status**: Complete

**Goal**: Runnable empty application with DI, config, logging, and CI pipeline.

### Deliverables
- [x] `pyproject.toml` with dependencies and tool config (ruff, black, mypy, import-linter)
- [x] `src/musicvault/` package structure per v3 layout (`models/`, `core/`, `db/`, `services/`, `workers/`, `plugins/`, `gui/`)
- [x] `core/config.py`, `container.py`, `logging.py`, `paths.py`, `exceptions.py`, `event_bus.py`
- [x] `app.py`, `__main__.py`
- [x] `config/defaults.json`
- [x] `tests/conftest.py` + 43 tests (unit + integration)
- [x] `.github/workflows/ci.yml` (ruff, black, mypy, pytest) and `release.yml`
- [x] `CONTRIBUTING.md`

### Acceptance Criteria
- [x] `python -m musicvault` exits 0, prints version
- [x] `pytest` passes (43/43, 97% coverage)
- [x] `mypy src/ --strict` passes (0 errors, 29 files)
- [x] `ruff check` and `black --check` pass
- [x] `lint-imports` passes (3/3 contracts kept)
- [x] GitHub Actions green on push (verified: https://github.com/oceanmasterza/MusicVault/actions)
- [x] Git commit: `feat: project scaffold with CI pipeline`

### Notes
- **Python version corrected to 3.14+** (was 3.13 at initial scaffold time). Discovered
  before writing any Phase 2 database code: `uuid.uuid7()` — used to generate every
  primary key in the schema — was only added to the standard library in Python 3.14,
  not 3.12 as the original architecture notes incorrectly claimed. Since 3.14 was
  already the only version installed in this environment, and using the stdlib
  implementation avoids a third-party dependency for the single most-used primitive
  in the codebase, the project now targets `>=3.14` everywhere: `pyproject.toml`,
  CI workflows, and all architecture docs. See [12-pipeline-engine-v3.md](12-pipeline-engine-v3.md#uuid-storage-v7-as-blob16).
- `event_bus.py` and `container.py` were added in Phase 1 (ahead of their originally
  planned phase) because `core/` is where they live in the v3 folder layout and the
  DI container needs *something* to hold from the first commit.

**Handoff point**: Switch to implementation-focused model for Phases 2+.

---

## Phase 2: Database Layer

**Status**: Complete

**Goal**: SQLAlchemy Core tables, Alembic migrations, UUID schema, job queue tables.

### Key Deliverables
- [x] `db/tables.py` — Core table definitions (the 15 fully-specified v2 tables; see
  scope note below)
- [x] `db/uuid_utils.py` — `uuid7()` generation + `uuid_to_blob` / `blob_to_uuid` conversion helpers
- [x] `db/engine.py` — engine factory + PRAGMA setup (see [12-pipeline-engine-v3.md](12-pipeline-engine-v3.md))
- [x] Alembic migration `0001_initial_schema`
- [x] `db/repositories/base.py` — generic batch upsert helper (Core, SQLite upsert)
- [x] Job, review, rules, file_identity repositories
- [x] Minimal entities pulled forward from Phase 3 (`Job`, `ReviewItem`, `Rule` in
  `models/entities/`; `FileIdentity` in `models/value_objects/`) — needed as the
  return type for this phase's repositories; the *richer* domain models (Track,
  Album, Artist, QualityScorer, DuplicateMatcher, rules AST evaluation) remain in
  Phase 3 as originally scoped
- [x] Migrations wired into `Container.bootstrap` (`core/container.py`) so the
  database is auto-created and migrated to head on every application startup,
  with the four repositories constructed and attached to the container

### Scope Decisions (recorded 2026-07-15, confirmed with user before implementation)
1. **Only 4 repositories now**: job, review, rule, file_identity — matching the
   original deliverable list exactly. Track/Album/Artist repositories wait for
   Phase 3, since they depend on domain services (quality scoring, duplicate
   matching) that don't exist yet.
2. **"Batch upsert 500 tracks < 1 second" acceptance criterion is deferred** to
   Phase 3, when a Track repository exists to literally test that claim. For
   Phase 2, the same generic batch-upsert mechanism is proven against the `jobs`
   table instead (see acceptance criteria below).
3. **The single-writer DB thread (`db/writer.py`) is deferred to Phase 4.** It
   exists to prevent concurrent workers from corrupting SQLite via simultaneous
   writes — but no concurrent workers exist until Phase 4. Building it now, with
   nothing to test it against, would be unverifiable. Phase 2 repositories write
   directly and synchronously, which is safe with a single writer thread (the
   only thing running so far).
4. **5 tables deferred — undocumented, not guessed.** `artwork`, `track_artwork`,
   `album_artwork`, `plugin_state`, and `library_stats` were referenced in
   `03-database-schema.md` as "unchanged from v1," but the v1 document no longer
   exists and their column definitions were never actually written down. Rather
   than invent a schema without a real spec, these are deferred to the phases
   that actually need them (11, 6/15, 13 respectively) and will be designed
   properly at that time. See the note in
   [03-database-schema.md](03-database-schema.md#artwork-plugins-statistics).

### Acceptance Criteria
- [x] DB auto-created on first run with all 15 fully-specified v2 tables
- [x] UUID v7 generated for all PKs
- [x] Batch upsert 500 rows into `jobs` < 1 second (see Scope Decision 2)
- [x] Alembic upgrade/downgrade works (round-trip creates and drops all tables cleanly)
- [x] `pytest` passes (127/127, 98% coverage)
- [x] `mypy`, `ruff check`, `black --check` pass
- [x] `lint-imports` passes (3/3 contracts kept)
- [x] GitHub Actions green on push (verified: https://github.com/oceanmasterza/MusicVault/actions/runs/29395697039)
- [x] Git commit: `feat: Phase 2 database layer with UUIDv7, Alembic migrations, and repositories`

### Notes
- **`DatabaseError` added to `core/exceptions.py`** so `db/migrations/runner.py` can
  translate Alembic/SQLAlchemy failures (locked files, missing directories, corrupt
  databases) into the application's own exception hierarchy — callers (currently
  `Container.bootstrap`, eventually the GUI's startup error dialog) only need to
  catch `MusicVaultError`.
- **`Container.close()` added** to dispose the database engine's connection pool.
  `python -m musicvault` calls it before exiting; the test suite's `container`
  fixture calls it on teardown so tests don't leak SQLite connections into later
  test cases.
- Repository tests live under `tests/unit/db/repositories/`, with a shared
  `conftest.py` providing a schema-initialized temp database plus `library_id`/
  `track_id` fixtures (inserted directly via Core, since `LibraryRepository`/
  `TrackRepository` don't exist until Phase 3) to satisfy the foreign keys that
  `jobs`, `review_items`, `rules`, and `file_identity` all require.

---

## Phase 3: Domain Models

**Status**: Complete

**Goal**: Pure domain entities, value objects, domain services.

### Key Deliverables
- [x] `Track`, `Album`, `Artist` entities + `LibraryZone` enum
      (`models/entities/`), matching `03-database-schema.md` column-for-column
- [x] `TrackRepository`, `AlbumRepository`, `ArtistRepository`
      (`db/repositories/`) — `TrackRepository`'s method names
      (`get_by_id`, `get_by_path`, `get_by_library`, `upsert_batch`,
      `update_zone`) follow the protocol documented in `04-service-layer.md`
      exactly
- [x] `QualityScorer` + `QualityWeights` (`models/services/`) — matches the
      exact example scores in `09-testing-strategy.md` (FLAC 24-bit → 100,
      FLAC 16-bit → 95, MP3 320 → 70); see scope note below for the
      additional brackets
- [x] `RenameEngine.clean_filename` (`models/services/`) — matches the 3
      documented scene-name-cleanup examples in `09-testing-strategy.md`
      exactly
- [x] Rules AST: `RuleNode`/`ConditionLeaf`/`AndNode`/`OrNode` + `parse_conditions`
      (`models/value_objects/rule_condition.py`), implementing the AST
      evaluation approach from `12-pipeline-engine-v3.md`
- [x] `RuleAction`, `FieldConfidence` value objects
      (`models/value_objects/`), matching `10-revision-v2.md` and
      `04-service-layer.md` respectively
- [x] All Phase 3 repositories wired into `Container.bootstrap`
- [x] 100% unit test coverage on every domain service
      (`quality_scorer.py`, `rename_engine.py`, `rule_condition.py`)

### Scope Decisions (recorded 2026-07-15, confirmed with user before implementation)
1. **`DuplicateMatcher` and `OrganizeEngine` deferred to Phases 9 and 10.**
   The original Phase 3 deliverable list included both, but neither has an
   actual specified algorithm anywhere in the architecture docs (no
   documented duplicate-matching thresholds, no documented folder-structure
   template syntax) — and both are *re-listed* as deliverables of their own
   dedicated phases, where the docs describe real consumers and behavior
   (`duplicate_groups` storage + quality-based best-track selection for
   Phase 9; the zone state machine + auto-approve threshold for Phase 10).
   Building them now would mean guessing at behavior those phases would
   likely have to redesign anyway. `QualityScorer` and `RenameEngine`, by
   contrast, both have concrete example-based specs in
   `09-testing-strategy.md` and no such dependency, so they stayed in scope.
2. **`QualityWeights` brackets beyond the 3 documented examples are this
   implementation's own fill-in**, not a documented formula. FLAC
   24-bit/16-bit and MP3 320 are exact per `09-testing-strategy.md`; the
   MP3 256/192/128 and AAC 256/128 brackets, and the `default_lossy`
   fallback, are reasonable defaults exposed as named, overridable fields
   on `QualityWeights` — see the module docstring in
   `models/services/quality_scorer.py`.
3. **`RuleCondition`'s AST nodes are pure value objects with no wired
   consumer yet.** `parse_conditions`/`RuleNode.evaluate` operate on a
   plain `Mapping[str, Any]` context rather than a typed `RuleContext`,
   because building the real context (track fields + `has_lossless_duplicate`
   and other duplicate-detection flags) requires `DuplicateMatcher`, which
   doesn't exist until Phase 9. `Rule.conditions`/`Rule.actions` (Phase 2)
   remain plain parsed JSON — the AST is a typed *parse* of that same JSON,
   used by whichever service actually evaluates rules (`RulesEngine`, Phase 8).
4. **Fixed a YAML example inconsistency** in `12-pipeline-engine-v3.md`
   ("Rules Engine — AST Evaluation"): it used `op`/`type`/`params` as key
   names, which didn't match the actual `RuleCondition`/`RuleAction`
   dataclass fields (`operator`/`action_type`/`parameters`) documented in
   `10-revision-v2.md` and implemented here. Corrected to keep the example
   consistent with the code.

### Acceptance Criteria
- [x] `Track`/`Album`/`Artist` entities round-trip every documented column
      through their repositories
- [x] `QualityScorer` reproduces all documented example scores exactly,
      including custom-weight overrides
- [x] `RenameEngine.clean_filename` reproduces all 3 documented examples exactly
- [x] Rules AST parses and evaluates the documented example rule
      (archive MP3 when FLAC exists) correctly
- [x] `pytest` passes (213/213, 99% coverage overall; 100% on every domain
      service module)
- [x] `mypy`, `ruff check`, `black --check` pass
- [x] `lint-imports` passes (3/3 contracts kept)
- [x] GitHub Actions green on push (verified: https://github.com/oceanmasterza/MusicVault/actions/runs/29398619948)
- [x] Git commit: `feat: Phase 3 domain models — Track/Album/Artist, QualityScorer, RenameEngine, rules AST`

### Notes
- `Track.zone`/`LibraryZone` lives in `models/entities/track.py` rather than
  a shared "zones" module — nothing else needs it yet, and it can move if a
  second consumer appears in Phase 10.
- `TrackRepository.upsert_batch` returns the row count, matching how many
  rows SQLite's `INSERT ... ON CONFLICT DO UPDATE` guarantees end up present
  (each input row is either newly inserted or updated — always exactly one
  resulting row), so no round-trip query is needed just to count.

---

## Phase 4: Job Dispatcher + Scanner/Hash Workers

**Status**: Complete

**Goal**: Persistent job queue with scanner and hash workers.

### Key Deliverables
- [x] `PipelineConfig` (`core/config.py`) — schema v1→v2 migration adds
      batch size, flush interval, worker pool size, and retry backoff
      tunables, all with defaults matching `08-performance.md`
- [x] `WriteDTO` + `DatabaseWriter` (`db/writer.py`) — single-writer
      background thread that batches worker-submitted rows into large
      transactions, so concurrent workers never write SQLite directly
- [x] `JobRepository.claim_pending` — atomic claim (one transaction:
      select-and-mark-`running`) plus `recover_orphaned`,
      `promote_due_retries`, `reset_for_retry`, and the aggregation
      queries `JobStatsDTO` needs
- [x] `JobQueueService` (`services/job_queue_service.py`) —
      enqueue/claim/complete/fail (exponential backoff)/cancel/retry/
      recover/stats, orchestrating `JobRepository`
- [x] `ScannerWorker` (`workers/io/scanner_worker.py`, I/O-bound,
      `ThreadPoolExecutor`) — walks a directory, upserts `Track` rows via
      `DatabaseWriter`, enqueues `hash_file` for each audio file found
- [x] `HashWorker` + `compute_hash` (`workers/cpu/hash_worker.py`,
      CPU-bound, `ProcessPoolExecutor`) — `compute_hash` is a pure,
      picklable function (SHA-256 + size + mtime only); `HashWorker`
      persists the result and chains to `fingerprint_file` only when the
      content hash actually changed
- [x] `JobDispatcher` (`services/job_dispatcher.py`) — polls
      `JobQueueService`, dispatches `scan_directory`/`hash_file` jobs to
      their respective pools, and exposes `recover()` for startup crash
      recovery
- [x] Crash recovery: `JobDispatcher.recover()` (→
      `JobQueueService.recover_orphaned`) resets any job left `running`
      by a previous crash back to `retry`
- [x] Pipeline chaining: `scan_directory` → `hash_file` → `fingerprint_file`
      (the last hop enqueues the job but `FingerprintWorker` itself is
      Phase 5)
- [x] Wired into `Container.bootstrap` — the database writer and
      dispatcher start automatically on every application startup, after
      crash recovery runs

### Scope Decisions (recorded 2026-07-15, confirmed with user before implementation)
1. **Built and verified in 7 small increments** rather than as one large
   change, per user request: `PipelineConfig` → `DatabaseWriter` →
   `JobRepository.claim_pending` → `JobQueueService` → `ScannerWorker` →
   `HashWorker` → `JobDispatcher` → `Container` wiring. Each increment was
   fully tested (unit tests green, coverage checked) before the next began.
2. **`JobQueueService` does not route job-status writes through
   `DatabaseWriter`.** Job bookkeeping (`enqueue`, `mark_completed`, etc.)
   is low-volume and latency-sensitive (the dispatcher needs to see a
   claim's effect immediately), so it writes synchronously through
   `JobRepository`. `DatabaseWriter` batching is reserved for the
   high-volume domain rows (`tracks`, `file_identity`) that `ScannerWorker`/
   `HashWorker` produce, which is exactly where batching earns its keep at
   100k–1M-track scale.
3. **`Container.bootstrap` starts the dispatcher automatically**, not just
   crash recovery. This is safe even with nothing yet enqueuing jobs in
   Phase 4: `ThreadPoolExecutor`/`ProcessPoolExecutor` only spawn actual
   OS threads/processes lazily on first `submit()`, so an idle dispatcher
   costs one lightweight polling thread and zero worker processes.
   `Container.close()` stops the dispatcher (waiting for in-flight work)
   and the writer before disposing the engine.

### Acceptance Criteria
- [x] A `scan_directory` job walks a real directory, upserts `Track` rows,
      and enqueues one `hash_file` job per audio file found
- [x] A `hash_file` job computes a SHA-256 hash in a worker *process*
      (verified `ProcessPoolExecutor` behaves correctly under pytest on
      Windows) and only enqueues `fingerprint_file` when the content hash
      changed
- [x] A job left `running` by a simulated crash is reset to `retry` by
      `Container.bootstrap` on the next startup, before any new work is
      dispatched
- [x] `DatabaseWriter` batches multiple DTOs per flush and logs (rather
      than crashes) on a failed batch, so one bad row never kills the
      writer thread
- [x] `pytest` passes (282/282, 99% coverage overall; 100% on every
      Phase 4 module)
- [x] `mypy`, `ruff check`, `black --check` pass
- [x] `lint-imports` passes (3/3 contracts kept)
- [x] GitHub Actions green on push (verified: https://github.com/oceanmasterza/MusicVault/actions/runs/29442968257)
- [x] Git commit: `feat: Phase 4 job dispatcher + scanner/hash workers`

### Notes
- `TrackRepository.to_row`/`FileIdentityRepository.to_row` are public
  static methods added so `ScannerWorker`/`HashWorker` can build
  `WriteDTO` rows through the same entity-to-row mapping the repositories'
  own `upsert`/`upsert_batch` use, instead of duplicating that logic.
- `ScannerWorker` uses `dataclasses.replace` on the existing `Track` (when
  one exists) rather than constructing a fresh one, so a rescan only
  updates filesystem-derived fields (path, size, mtime) and never
  overwrites metadata a later phase's arbitrator has already resolved.
- `services/dto/job_dto.py` holds `JobCreate`/`JobStatsDTO` — `JobStatsDTO`
  is assembled in `JobQueueService` from raw aggregates `JobRepository`
  returns, not inside the repository itself, because `db` cannot import
  from `services` (`lint-imports` contract "DB layer stays below services
  and workers").

---

## Phase 5: Fingerprint Worker

**Status**: Complete

**Goal**: Chromaprint generation with permanent storage and skip logic.

### Key Deliverables
- [x] `FingerprintProvider` protocol + `FingerprintResult`
      (`models/interfaces/fingerprint.py`)
- [x] Built-in Chromaprint provider (`plugins/builtin/chromaprint/`) wrapping
      `pyacoustid.fingerprint_file` / `fpcalc`
- [x] `FingerprintWorker` + `compute_fingerprint` (`workers/cpu/`, shared
      CPU `ProcessPoolExecutor` with hash) — persists
      `fingerprint_data` / `fingerprint_duration` / `fingerprint_hash` on
      `file_identity`, chains to `identify_metadata`
- [x] Skip unchanged files — scanner size/mtime skip + hash content-hash
      skip (Phase 4) plus a defensive "already fingerprinted" early-complete
      path for crash-recovery re-delivery
- [x] `HashWorker` fix — preserves existing fingerprint fields when the
      content hash is unchanged, and passes `file_path` into
      `fingerprint_file` job payloads
- [x] Wired into `JobDispatcher` + `Container.bootstrap`
- [x] AcoustID *HTTP* lookup deliberately deferred to Phase 6
      (MetadataWorker / metadata providers) — Chromaprint generation is
      the FingerprintProvider; AcoustID's MusicBrainz ID lookup is
      metadata identification

### Scope Decisions (recorded 2026-07-16)
1. **AcoustID HTTP deferred to Phase 6.** The roadmap listed "AcoustID
   plugin" under Phase 5, but the pipeline docs assign AcoustID HTTP to
   MetadataWorker (I/O tier). Phase 5 ships Chromaprint generation + the
   FingerprintProvider protocol; storing `acoustid_id`/`acoustid_score`
   happens when metadata identification is built.
2. **Shared CPU ProcessPool** for hash and fingerprint (both Tier 1) —
   one pool sized by `hash_worker_processes`, not a second pool.
3. **Tests mock Chromaprint** — CI runners may not have `fpcalc`; unit
   tests monkeypatch `generate_chromaprint` / `acoustid.fingerprint_file`.

### Acceptance Criteria
- [x] A `fingerprint_file` job stores Chromaprint fields on `file_identity`
      and enqueues `identify_metadata`
- [x] Unchanged files are skipped by the existing scan/hash chain; already-
      fingerprinted re-deliveries complete without recomputing
- [x] `pytest` passes (298/298, 98% coverage overall; 100% on Phase 5 modules)
- [x] `mypy`, `ruff check`, `black --check` pass
- [x] `lint-imports` passes (3/3 contracts kept)
- [x] GitHub Actions green on push (verified: https://github.com/oceanmasterza/MusicVault/actions/runs/29473149169)
- [x] Git commit: `feat: Phase 5 FingerprintWorker with Chromaprint persistence`

---

## Phase 6: Metadata Arbitrator

**Status**: Complete

**Goal**: Multi-provider metadata with per-field confidence.

### Key Deliverables
- [x] `MetadataProvider` protocol + `FingerprintData` / `MetadataQuery` /
      `ProviderResult` / `ArbitrationResult` (`models/interfaces/metadata.py`)
- [x] `MetadataArbitrator` — cascade AcoustID → MusicBrainz by ID →
      MusicBrainz tags / local tags / filename; per-field winners;
      `overall_confidence = min(field confidences)`; `needs_review` when
      below threshold
- [x] Built-in providers: AcoustID (HTTP), MusicBrainz, local tags
      (Mutagen), filename parser — Discogs deferred
- [x] `MetadataConfidenceRepository` — wipe-and-write winners into
      `metadata_confidence`
- [x] `MetadataWorker` (`workers/io/`) — I/O Tier 2; persists track
      fields + confidence rows + optional `acoustid_*` on `file_identity`;
      does **not** enqueue artwork/duplicates/rules yet (Phase 8+)
- [x] `MetadataConfig` + schema v2→v3 (`provider_order`,
      `enabled_providers`, `confidence_threshold`, `acoustid_api_key`,
      `metadata_worker_threads`)
- [x] `PluginManager` + explicit provider wiring in `Container.bootstrap`
- [x] `JobDispatcher` claims `identify_metadata` on a dedicated I/O
      thread pool (claim-all-then-dispatch so nested enqueues wait a cycle)

### Scope Decisions (recorded 2026-07-16)
1. **AcoustID is a MetadataProvider** (HTTP lookup), not a FingerprintProvider —
   Chromaprint generation stayed in Phase 5.
2. **Cascade inside the arbitrator** rather than a separate orchestrator.
3. **MVP providers only** — AcoustID, MusicBrainz, local tags, filename;
   Discogs later.
4. **No downstream enqueue** of `fetch_artwork` / `detect_duplicates` /
   `evaluate_rules` until those workers exist.
5. **`tracks.needs_review` + `overall_confidence` only** — `review_items`
   creation delivered in Phase 7.
6. **`overall_confidence = min(field confidences)`**.

### Acceptance Criteria
- [x] An `identify_metadata` job resolves providers, writes track fields +
      `metadata_confidence`, and sets `needs_review` when below threshold
- [x] Provider enablement / order / AcoustID API key configurable via
      `MetadataConfig` (schema v3)
- [x] `pytest` passes (333/333)
- [x] `mypy`, `ruff check`, `black --check` pass
- [x] `lint-imports` passes (3/3 contracts kept)
- [x] GitHub Actions green on push (verified: https://github.com/oceanmasterza/MusicVault/actions/runs/29475808849)
- [x] Git commit: `feat: Phase 6 MetadataArbitrator + metadata providers`

---

## Phase 7: Review Queue

**Goal**: Human approval gate for uncertain metadata.

### Key Deliverables
- `ReviewQueueService`
- Auto-create review items when confidence < threshold
- Approve/reject/defer/edit workflow

### Implementation notes (service layer)
- `ReviewQueueService` — create / get_pending / get_by_type / approve /
  reject / defer / approve_with_edits; idempotent upsert on
  `(track_id, review_type)` for pending items
- `MetadataWorker` creates a `review_items` row when
  `ArbitrationResult.needs_review` (classification: weak artist → weak
  album → provider conflict → catch-all unknown_artist)
- Approve clears `tracks.needs_review`; does **not** move zones (Phase 10)
- Reject / defer leave `needs_review`; deferred items leave the pending list
- `ReviewItemAddedEvent` on `EventBus` for future Qt badge refresh
- GUI review page is Phase 14; artwork / duplicates / rules enqueue still later

### Acceptance Criteria
- [x] Low-confidence identification creates a pending review item
- [x] Approve / reject / defer / approve_with_edits work via service API
- [x] Re-identify refreshes the same pending item (no duplicates)
- [x] Container wires `ReviewQueueService` into `MetadataWorker`
- [ ] CI green on GitHub Actions
- [x] Git commit: `feat: Phase 7 ReviewQueueService + metadata review items`

---

## Phase 8: Rules Engine

**Goal**: User-configurable automation rules.

### Key Deliverables
- `RulesEngine` with condition evaluation
- Default rules (archive MP3, detect VA, flag low quality)
- Rule CRUD via config/API (GUI in Phase 14)

---

## Phase 9: Duplicate Detection

**Goal**: Fingerprint/MBID/hash duplicate detection with quality ranking.

### Key Deliverables
- `DuplicateWorker`
- Duplicate group storage
- Quality-based best-track selection

---

## Phase 10: Organizer + Watch Folder

**Goal**: Staging zones, folder organization, incoming watch folder.

### Key Deliverables
- `OrganizerWorker`, `WatchFolderService`
- Zone state machine (incoming → staging → library)
- Auto-approve when confidence ≥ threshold

---

## Phase 11: Artwork Worker

**Goal**: Detect, download, embed artwork.

### Key Deliverables
- `ArtworkWorker`
- Cover Art Archive plugin
- Missing/low-res detection

---

## Phase 12: Rollback Engine

**Goal**: Reversible operations with snapshots.

### Key Deliverables
- `OperationOrchestrator` with rollback
- Zone-aware change history

---

## Phase 13: Reports

**Goal**: HTML, CSV, Excel, PDF reports.

---

## Phase 14: GUI

**Goal**: Full Qt6 interface including Review Queue, Job Monitor, Duplicate Viewer, Rules Editor.

---

## Phase 15: Media Server Plugins

**Goal**: Navidrome (with DB access), Jellyfin, Plex, and remaining servers.

---

## Phase 16: Packaging

**Goal**: PyInstaller + Windows installer. CI release workflow builds on tags.

---

## Milestone Summary

| Phase | Version | Key Deliverable |
|-------|---------|----------------|
| 0b | 0.0.1 | Architecture v2 revision |
| 1 | 0.1.0 | Scaffold + CI |
| 2 | 0.2.0 | SQLAlchemy Core + UUID schema |
| 3 | 0.3.0 | Domain models |
| 4 | 0.4.0 | Job queue + scanner |
| 5 | 0.5.0 | Fingerprint worker |
| 6 | 0.6.0 | Metadata arbitrator |
| 7 | 0.7.0 | Review queue |
| 8 | 0.8.0 | Rules engine |
| 9 | 0.9.0 | Duplicates |
| 10 | 0.10.0 | Staging + watch folder |
| 11 | 0.11.0 | Artwork |
| 12 | 0.12.0 | Rollback |
| 13 | 0.13.0 | Reports |
| 14 | 1.0.0-beta | Full GUI |
| 15 | 1.0.0-rc | Media servers |
| 16 | 1.0.0 | Windows installer |

## Risk Register (Updated)

| Risk | Impact | Mitigation |
|------|--------|------------|
| SQLAlchemy Core learning curve | Medium | Clear repository examples in Phase 2 |
| Job queue contention at 1M jobs | High | Batch claim, index on (status, job_type, priority) |
| UUID index size | Low | v7 time-sortable; acceptable overhead |
| Navidrome DB schema changes | Medium | Version-check; API fallback |
| Watch folder race conditions | Medium | Debounce 2s; enqueue only after file stable |
| Review queue overwhelming user | Medium | Auto-approve threshold configurable; bulk approve |
| Rule engine complexity | Medium | Start with simple conditions; expand gradually |
