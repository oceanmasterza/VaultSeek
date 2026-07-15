# 07 — Development Roadmap

## Principles

1. **Each phase compiles, runs, and passes tests** before the next begins
2. **Git commit after every milestone** with descriptive message
3. **CHANGELOG updated** with each phase
4. **No phase is skipped** — dependencies are sequential
5. **Vertical slices** where possible — deliver working features, not layers in isolation

## Phase Overview

```
Phase 0  ██████████ Architecture (CURRENT)
Phase 1  ░░░░░░░░░░ Project scaffold
Phase 2  ░░░░░░░░░░ Database layer
Phase 3  ░░░░░░░░░░ Domain models
Phase 4  ░░░░░░░░░░ Library scanner
Phase 5  ░░░░░░░░░░ Fingerprint engine
Phase 6  ░░░░░░░░░░ Metadata engine
Phase 7  ░░░░░░░░░░ Duplicates & quality
Phase 8  ░░░░░░░░░░ Organizer & rename
Phase 9  ░░░░░░░░░░ Artwork manager
Phase 10 ░░░░░░░░░░ Rollback engine
Phase 11 ░░░░░░░░░░ Reports
Phase 12 ░░░░░░░░░░ GUI
Phase 13 ░░░░░░░░░░ Plugins & Navidrome
Phase 14 ░░░░░░░░░░ Packaging & installer
```

---

## Phase 0: Architecture & Documentation

**Status**: In progress

### Deliverables
- [x] Architecture documentation (this directory)
- [x] README.md
- [x] CHANGELOG.md
- [x] .gitignore
- [ ] Initial git commit

### Acceptance Criteria
- All architecture documents reviewed and internally consistent
- Database schema covers all 20 features
- Service layer interfaces defined for all major use cases
- Plugin API specification complete

---

## Phase 1: Project Scaffold

**Goal**: Runnable empty application with DI, config, and logging.

### Deliverables
- `pyproject.toml` with all dependencies pinned
- `src/musicvault/` package structure (empty modules with docstrings)
- `core/config.py` — load, validate, migrate JSON config
- `core/container.py` — DI container wiring
- `core/logging.py` — Loguru setup with rotation
- `core/paths.py` — platform-specific app data directories
- `core/exceptions.py` — exception hierarchy
- `app.py` — bootstrap sequence
- `__main__.py` — entry point
- `config/defaults.json` — default configuration
- `tests/conftest.py` — shared fixtures
- `CONTRIBUTING.md`

### Acceptance Criteria
- `python -m musicvault` launches without error (prints version, exits)
- `pytest` runs (0 tests, 0 failures)
- `mypy src/` passes with strict mode
- Config loads from defaults, saves to `%APPDATA%/MusicVault/`
- Logs written to `%APPDATA%/MusicVault/logs/`
- Git commit: `feat: project scaffold with DI, config, and logging`

---

## Phase 2: Database Layer

**Goal**: SQLite database with full schema, migrations, and repository stubs.

### Deliverables
- SQLAlchemy ORM models for all tables (see 03-database-schema.md)
- Alembic migration: `001_initial_schema.py`
- `database/engine.py` — engine factory with WAL pragmas
- Repository implementations (CRUD for all entities)
- `tests/integration/test_database.py` — create DB, insert/query/delete

### Acceptance Criteria
- `python -m musicvault` auto-creates database on first run
- All tables created with correct indexes
- Repository round-trip tests pass for Track, Album, Artist
- Alembic upgrade/downgrade works
- Git commit: `feat: database layer with SQLAlchemy models and Alembic migrations`

---

## Phase 3: Domain Models & Repositories

**Goal**: Pure domain entities, value objects, and domain services.

### Deliverables
- Domain entities: `Track`, `Album`, `Artist`, `Artwork`, `DuplicateGroup`, `ScanSession`
- Value objects: `AudioFormat`, `QualityScore`, `FileHash`, `MetadataTags`, `OrganizePath`
- Domain services: `QualityScorer`, `DuplicateMatcher`, `RenameEngine`, `OrganizeEngine`
- Repository protocol definitions in `domain/interfaces/`
- Entity ↔ ORM model mapping
- Unit tests for all domain services

### Acceptance Criteria
- Domain layer has zero imports from infrastructure or GUI
- `QualityScorer` correctly ranks all format/bitrate combinations
- `RenameEngine` correctly cleans all scene naming patterns
- `OrganizeEngine` generates correct paths from rules
- `DuplicateMatcher` groups tracks by fingerprint/MBID/hash
- 100% unit test coverage on domain services
- Git commit: `feat: domain models, value objects, and domain services`

---

## Phase 4: Library Scanner

**Goal**: Multi-threaded scanner that ingests audio files into the database.

### Deliverables
- `AudioFileReader` (Mutagen) — read metadata from all supported formats
- `FileWalker` — recursive directory discovery with extension filter
- `HashCalculator` — MD5/SHA256 content hashes
- `ScannerService` — orchestrate scan with thread pool
- `ScanWorker` — QRunnable wrapper (for future GUI)
- Incremental scan support (mtime comparison)
- `tests/integration/test_scanner.py` — scan test fixture directory

### Acceptance Criteria
- Scans a directory of mixed-format audio files
- Correctly reads bitrate, duration, codec, channels, bit depth
- Detects embedded artwork presence
- Incremental scan skips unchanged files
- Processes ≥ 100 files/second on SSD
- Progress callback reports accurate counts
- Corrupt files logged and skipped (not crashed)
- Git commit: `feat: multi-threaded library scanner with incremental scan`

---

## Phase 5: Fingerprint Engine

**Goal**: Chromaprint fingerprinting and AcoustID identification.

### Deliverables
- `ChromaprintGenerator` — wrapper around `fpcalc` binary
- `AcoustIDClient` — API client with rate limiting
- `FingerprintService` — generate + lookup workflow
- AcoustID plugin (builtin)
- Fingerprint caching on disk
- `tests/integration/test_fingerprint.py`

### Acceptance Criteria
- Generates Chromaprint fingerprint for any supported audio file
- Looks up AcoustID and returns MusicBrainz recording IDs
- Handles missing `fpcalc` gracefully (warns user, disables fingerprinting)
- Rate-limits AcoustID API calls (3/second max)
- Caches results to avoid repeat lookups
- Git commit: `feat: Chromaprint fingerprinting and AcoustID identification`

---

## Phase 6: Metadata Engine

**Goal**: MusicBrainz-driven metadata identification and correction.

### Deliverables
- MusicBrainz plugin (builtin) — fingerprint, tag, and ID lookup
- `MetadataService` — identify, match, apply workflow
- Fuzzy tag matching with RapidFuzz
- Metadata diff preview (old vs. new)
- Tag writing back to files (via Mutagen)
- `tests/integration/test_metadata.py` with recorded API responses

### Acceptance Criteria
- Identifies tracks by fingerprint even with wrong filenames
- Fixes artist, album, track number, genre, year, composer
- Writes MusicBrainz IDs to file tags
- Respects MusicBrainz rate limit (1 req/sec)
- Preview shows exactly what will change before applying
- Unknown tracks marked correctly
- Git commit: `feat: MusicBrainz metadata identification and correction`

---

## Phase 7: Duplicate Detection & Quality Scoring

**Goal**: Detect duplicates by fingerprint/MBID/hash and rank by quality.

### Deliverables
- `DuplicateService` — full detection pipeline
- `QualityScorer` integration with configurable weights
- Duplicate group storage and resolution
- Detection of: same track different encoding, remasters, deluxe editions
- `tests/integration/test_duplicates.py`

### Acceptance Criteria
- Detects exact duplicates (same hash)
- Detects same recording different format (fingerprint + MBID)
- Distinguishes remasters (different MB release group)
- Quality scoring ranks 24-bit FLAC > 16-bit FLAC > 320 MP3 correctly
- "Keep best" resolution marks duplicates and calculates storage savings
- Git commit: `feat: duplicate detection and quality scoring engine`

---

## Phase 8: Folder Organization & Rename Engine

**Goal**: Configurable folder structures and intelligent file renaming.

### Deliverables
- `OrganizerService` — preview and execute folder moves
- `RenameService` — preview and execute file renames
- Default organize rules (FLAC/MP3/Various Artists/Singles/Classical)
- Scene name cleaning patterns (configurable regex list)
- Multi-disc folder support
- `tests/integration/test_organizer.py`, `test_rename.py`

### Acceptance Criteria
- Default rules produce correct folder structure
- Scene-named files correctly cleaned
- Multi-disc albums organized into Disc 1, Disc 2 folders
- Preview shows all moves before executing
- Rollback restores original paths (requires Phase 10, stub for now)
- Git commit: `feat: folder organization and rename engine`

---

## Phase 9: Artwork Manager

**Goal**: Detect, download, embed, and replace artwork.

### Deliverables
- Cover Art Archive plugin (builtin)
- `ArtworkService` — missing detection, download, embed, replace
- `ArtworkProcessor` (Pillow) — resize, validate, format conversion
- Artwork report (albums missing art, low resolution)
- `tests/integration/test_artwork.py`

### Acceptance Criteria
- Detects albums without artwork (no embedded, no downloaded)
- Downloads front cover from Cover Art Archive by MB release ID
- Embeds artwork into audio files (FLAC, MP3, M4A)
- Replaces artwork below configurable resolution threshold
- Artwork report lists all missing/low-res albums
- Git commit: `feat: artwork detection, download, and embedding`

---

## Phase 10: Rollback Engine

**Goal**: Every operation is reversible with full undo support.

### Deliverables
- `RollbackService` — snapshot creation and restoration
- `OperationOrchestrator` — gate all mutating operations
- `change_history` recording for every field change
- Snapshot compression and storage
- Undo via UI and CLI
- `tests/integration/test_rollback.py`

### Acceptance Criteria
- Metadata fix can be fully rolled back (tags restored)
- File rename/move can be rolled back (original paths restored)
- Artwork embed can be rolled back (original artwork restored)
- Multiple sequential rollbacks work correctly
- Operations without snapshots cannot be rolled back (safety check)
- Git commit: `feat: rollback engine with operation orchestration`

---

## Phase 11: Reports

**Goal**: Generate HTML, CSV, Excel, and PDF reports.

### Deliverables
- `ReportService` — report generation for all report types
- HTML reports with embedded CSS (self-contained files)
- CSV export for all data types
- Excel export via `openpyxl`
- PDF export via `weasyprint` or `reportlab`
- Report types: library stats, duplicates, missing artwork, unknown, corrupt, storage

### Acceptance Criteria
- HTML report renders correctly in browser with stats, tables, and charts
- CSV export opens correctly in Excel with proper encoding (UTF-8 BOM)
- PDF report is printable and professional
- Reports generate in < 30 seconds for 100K tracks
- Git commit: `feat: report generation (HTML, CSV, Excel, PDF)`

---

## Phase 12: GUI

**Goal**: Full Qt6 dark-mode interface with all pages.

### Deliverables
- `MainWindow` with sidebar navigation
- All 11 views and ViewModels
- Custom widgets: `TrackTable`, `AlbumGrid`, `ProgressPanel`, `OperationPreview`
- Dark theme QSS
- All dialogs (scan, preview, confirm, settings)
- Worker integration for all long-running operations
- `pytest-qt` tests for ViewModels

### Acceptance Criteria
- Application launches with dark-themed GUI
- Dashboard shows correct library statistics
- Library page lists tracks with sort, filter, search
- Scan runs with live progress in status bar
- Metadata fix shows preview dialog before applying
- Duplicates page shows groups with quality comparison
- Settings page edits and saves all configuration sections
- All long-running operations run in background without freezing UI
- Git commit: `feat: complete Qt6 GUI with dark theme`

---

## Phase 13: Plugin System & Navidrome Integration

**Goal**: Formalized plugin loading and Navidrome media server integration.

### Deliverables
- `PluginManager` — entry point discovery, loading, lifecycle
- Plugin settings UI (enable/disable, configure)
- Navidrome plugin — connect, validate, rescan
- Plugin caching layer
- Third-party plugin documentation
- `tests/integration/test_plugins.py`, `test_navidrome.py`

### Acceptance Criteria
- Built-in plugins discovered and loaded at startup
- Plugins can be enabled/disabled without restart
- Plugin configuration persisted in database
- Navidrome: connect, list albums, detect metadata mismatches
- Navidrome: trigger rescan after local changes
- Failed plugin does not crash application
- Git commit: `feat: plugin system and Navidrome integration`

---

## Phase 14: Packaging & Windows Installer

**Goal**: Distributable Windows application.

### Deliverables
- PyInstaller spec (`packaging/musicvault.spec`)
- Bundled dependencies (FFmpeg, fpcalc)
- Inno Setup installer script
- Auto-update check (GitHub Releases API)
- Code signing documentation
- CI release workflow (GitHub Actions)

### Acceptance Criteria
- `MusicVault.exe` runs on clean Windows 10/11 without Python installed
- Installer creates Start Menu shortcut and desktop icon
- Uninstaller removes all files cleanly
- Application data preserved on uninstall
- Installer size < 100 MB
- Git commit: `feat: Windows packaging and installer`

---

## Milestone Summary

| Phase | Version | Key Deliverable | Est. Duration |
|-------|---------|----------------|---------------|
| 0 | 0.0.0 | Architecture docs | 1 week |
| 1 | 0.1.0 | Runnable scaffold | 1 week |
| 2 | 0.2.0 | Database layer | 1 week |
| 3 | 0.3.0 | Domain models | 2 weeks |
| 4 | 0.4.0 | Library scanner | 2 weeks |
| 5 | 0.5.0 | Fingerprint engine | 1 week |
| 6 | 0.6.0 | Metadata engine | 2 weeks |
| 7 | 0.7.0 | Duplicates & quality | 2 weeks |
| 8 | 0.8.0 | Organizer & rename | 2 weeks |
| 9 | 0.9.0 | Artwork manager | 1 week |
| 10 | 0.10.0 | Rollback engine | 2 weeks |
| 11 | 0.11.0 | Reports | 1 week |
| 12 | 1.0.0-beta | Full GUI | 3 weeks |
| 13 | 1.0.0-rc | Plugins & Navidrome | 2 weeks |
| 14 | 1.0.0 | Windows installer | 1 week |

**Total estimated duration**: ~24 weeks (6 months) for a single experienced developer.

## Risk Register

| Risk | Impact | Mitigation |
|------|--------|------------|
| Chromaprint binary not available on all systems | Fingerprinting disabled | Bundle `fpcalc` in installer; graceful fallback |
| MusicBrainz rate limiting slows bulk identification | Poor UX for large libraries | Aggressive caching, batch mode, offline queue |
| SQLite performance at 1M+ tracks | Slow queries | WAL mode, indexes, pagination, materialized stats |
| PyInstaller bundle size | Large download | Exclude unused Qt modules, UPX compression |
| Mutagen tag writing breaks some files | Data loss | Always snapshot before write; validate after write |
| Plugin API changes break third-party plugins | Ecosystem friction | Semantic versioning, deprecation warnings, adapter layer |
