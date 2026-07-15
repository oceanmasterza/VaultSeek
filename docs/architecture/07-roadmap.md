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
Phase 0b  ██████████ Architecture v2 revision (CURRENT)
Phase 1   ░░░░░░░░░░ Scaffold + CI
Phase 2   ░░░░░░░░░░ Database (Core + UUID + jobs)
Phase 3   ░░░░░░░░░░ Domain models + repositories
Phase 4   ░░░░░░░░░░ Job dispatcher + scanner/hash workers
Phase 5   ░░░░░░░░░░ Fingerprint worker + persistence
Phase 6   ░░░░░░░░░░ Metadata arbitrator + providers
Phase 7   ░░░░░░░░░░ Review queue + confidence scoring
Phase 8   ░░░░░░░░░░ Rules engine
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
- Local development/verification used Python 3.14 (only version available in this
  environment); `pyproject.toml` still targets `>=3.13` per the architecture, and CI
  pins `3.13` explicitly via `actions/setup-python`. Revisit if 3.13-specific behavior
  ever diverges from 3.14.
- `event_bus.py` and `container.py` were added in Phase 1 (ahead of their originally
  planned phase) because `core/` is where they live in the v3 folder layout and the
  DI container needs *something* to hold from the first commit.

**Handoff point**: Switch to implementation-focused model for Phases 2+.

---

## Phase 2: Database Layer

**Goal**: SQLAlchemy Core tables, Alembic migrations, UUID schema, job queue tables.

### Key Deliverables
- `infrastructure/database/tables.py` — Core table definitions
- Alembic migration `001_initial_schema_v2`
- Repository implementations (Core, batch upsert)
- Job, review, rules, file_identity repositories

### Acceptance Criteria
- DB auto-created on first run with all v2 tables
- UUID v7 generated for all PKs
- Batch upsert 500 tracks < 1 second
- Alembic upgrade/downgrade works

---

## Phase 3: Domain Models

**Goal**: Pure domain entities, value objects, domain services.

### Key Deliverables
- Entities with UUID identities
- `QualityScorer`, `DuplicateMatcher`, `RenameEngine`, `OrganizeEngine`
- `RuleCondition`, `RuleAction`, `FieldConfidence`
- 100% unit test coverage on domain services

---

## Phase 4: Job Dispatcher + Scanner/Hash Workers

**Goal**: Persistent job queue with scanner and hash workers.

### Key Deliverables
- `JobQueueService`, `JobDispatcher`
- `ScannerWorker`, `HashWorker`
- Crash recovery (orphaned job reset)
- Pipeline chaining (scan → hash → fingerprint)

---

## Phase 5: Fingerprint Worker

**Goal**: Chromaprint generation with permanent storage and skip logic.

### Key Deliverables
- `FingerprintWorker`
- `file_identity` persistence
- Skip unchanged files
- AcoustID plugin

---

## Phase 6: Metadata Arbitrator

**Goal**: Multi-provider metadata with per-field confidence.

### Key Deliverables
- `MetadataArbitrator`
- MusicBrainz + filename parser plugins
- `metadata_confidence` storage
- Provider priority configuration

---

## Phase 7: Review Queue

**Goal**: Human approval gate for uncertain metadata.

### Key Deliverables
- `ReviewQueueService`
- Auto-create review items when confidence < threshold
- Approve/reject/defer/edit workflow

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
