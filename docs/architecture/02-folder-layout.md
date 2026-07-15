# 02 — Project Folder Layout

## Repository Structure

```
MusicVault/
├── .github/
│   └── workflows/
│       ├── ci.yml                  # pytest, mypy, lint on push/PR
│       └── release.yml             # PyInstaller build + artifact upload
│
├── docs/
│   ├── architecture/                 # This documentation set
│   ├── user-guide/                 # End-user documentation (Phase 12+)
│   └── api/                        # Generated API docs (Sphinx, Phase 13+)
│
├── src/
│   └── musicvault/
│       ├── __init__.py
│       ├── __main__.py             # Entry point: python -m musicvault
│       ├── app.py                  # Application bootstrap, DI container wiring
│       │
│       ├── core/                   # Cross-cutting concerns
│       │   ├── __init__.py
│       │   ├── config.py           # Config loading, validation, migration
│       │   ├── container.py        # Dependency injection container
│       │   ├── exceptions.py       # Application exception hierarchy
│       │   ├── logging.py          # Loguru setup
│       │   └── paths.py            # App data dirs, platform paths
│       │
│       ├── domain/                 # Pure business logic (no I/O)
│       │   ├── __init__.py
│       │   ├── entities/
│       │   │   ├── __init__.py
│       │   │   ├── track.py        # Track entity
│       │   │   ├── album.py        # Album entity
│       │   │   ├── artist.py       # Artist entity
│       │   │   ├── artwork.py      # Artwork entity
│       │   │   ├── fingerprint.py  # Fingerprint value object
│       │   │   ├── duplicate.py    # DuplicateGroup entity
│       │   │   └── scan.py         # ScanSession entity
│       │   ├── value_objects/
│       │   │   ├── __init__.py
│       │   │   ├── audio_format.py # Codec, bitrate, bit depth, sample rate
│       │   │   ├── quality_score.py
│       │   │   ├── file_hash.py
│       │   │   ├── metadata_tags.py
│       │   │   └── organize_path.py
│       │   ├── services/
│       │   │   ├── __init__.py
│       │   │   ├── quality_scorer.py
│       │   │   ├── duplicate_matcher.py
│       │   │   ├── rename_engine.py
│       │   │   └── organize_engine.py
│       │   └── interfaces/
│       │       ├── __init__.py
│       │       ├── repositories.py  # Repository protocols
│       │       ├── file_reader.py   # Audio file reading protocol
│       │       ├── fingerprint.py   # Fingerprint generation protocol
│       │       └── file_ops.py      # File move/rename/delete protocol
│       │
│       ├── application/            # Use case orchestration
│       │   ├── __init__.py
│       │   ├── scanner_service.py
│       │   ├── metadata_service.py
│       │   ├── fingerprint_service.py
│       │   ├── duplicate_service.py
│       │   ├── organizer_service.py
│       │   ├── rename_service.py
│       │   ├── artwork_service.py
│       │   ├── rollback_service.py
│       │   ├── report_service.py
│       │   ├── operation_orchestrator.py
│       │   └── dto/                # Data transfer objects for GUI
│       │       ├── __init__.py
│       │       ├── scan_dto.py
│       │       ├── track_dto.py
│       │       ├── duplicate_dto.py
│       │       └── report_dto.py
│       │
│       ├── infrastructure/         # External system implementations
│       │   ├── __init__.py
│       │   ├── database/
│       │   │   ├── __init__.py
│       │   │   ├── engine.py       # SQLAlchemy engine, session factory
│       │   │   ├── models.py       # SQLAlchemy ORM models
│       │   │   ├── migrations/     # Alembic migration scripts
│       │   │   │   ├── env.py
│       │   │   │   └── versions/
│       │   │   └── repositories/   # Repository implementations
│       │   │       ├── __init__.py
│       │   │       ├── track_repo.py
│       │   │       ├── album_repo.py
│       │   │       ├── artist_repo.py
│       │   │       ├── scan_repo.py
│       │   │       ├── duplicate_repo.py
│       │   │       ├── artwork_repo.py
│       │   │       ├── rollback_repo.py
│       │   │       └── change_history_repo.py
│       │   ├── audio/
│       │   │   ├── __init__.py
│       │   │   ├── mutagen_reader.py
│       │   │   ├── ffmpeg_probe.py
│       │   │   └── format_registry.py
│       │   ├── fingerprint/
│       │   │   ├── __init__.py
│       │   │   ├── chromaprint_gen.py
│       │   │   └── acoustid_client.py
│       │   ├── filesystem/
│       │   │   ├── __init__.py
│       │   │   ├── file_walker.py
│       │   │   ├── file_operations.py
│       │   │   └── safe_delete.py
│       │   ├── imaging/
│       │   │   ├── __init__.py
│       │   │   └── artwork_processor.py
│       │   └── http/
│       │       ├── __init__.py
│       │       └── rate_limited_client.py
│       │
│       ├── plugins/                # Plugin system
│       │   ├── __init__.py
│       │   ├── manager.py          # Discovery, loading, lifecycle
│       │   ├── registry.py         # Plugin type registry
│       │   ├── base.py             # Base plugin classes and protocols
│       │   └── builtin/            # Shipped plugins
│       │       ├── __init__.py
│       │       ├── musicbrainz/
│       │       ├── acoustid/
│       │       ├── navidrome/
│       │       ├── cover_art_archive/
│       │       └── discogs/        # Future
│       │
│       └── gui/                    # Presentation layer
│           ├── __init__.py
│           ├── main_window.py
│           ├── app.py              # QApplication setup, theme
│           ├── resources/          # Icons, QSS stylesheets, fonts
│           │   ├── icons/
│           │   ├── styles/
│           │   │   └── dark.qss
│           │   └── resources.qrc
│           ├── views/              # QWidget subclasses (dumb views)
│           │   ├── __init__.py
│           │   ├── dashboard_view.py
│           │   ├── library_view.py
│           │   ├── artists_view.py
│           │   ├── albums_view.py
│           │   ├── duplicates_view.py
│           │   ├── unknown_view.py
│           │   ├── artwork_view.py
│           │   ├── reports_view.py
│           │   ├── logs_view.py
│           │   ├── settings_view.py
│           │   └── plugins_view.py
│           ├── viewmodels/         # Presentation logic
│           │   ├── __init__.py
│           │   ├── base_viewmodel.py
│           │   ├── dashboard_vm.py
│           │   ├── library_vm.py
│           │   ├── scan_vm.py
│           │   ├── metadata_vm.py
│           │   ├── duplicates_vm.py
│           │   ├── artwork_vm.py
│           │   ├── reports_vm.py
│           │   ├── settings_vm.py
│           │   └── plugins_vm.py
│           ├── widgets/            # Reusable custom widgets
│           │   ├── __init__.py
│           │   ├── track_table.py
│           │   ├── album_grid.py
│           │   ├── progress_panel.py
│           │   ├── operation_preview.py
│           │   └── search_bar.py
│           └── workers/            # QRunnable / QThread workers
│               ├── __init__.py
│               ├── scan_worker.py
│               ├── metadata_worker.py
│               └── report_worker.py
│
├── tests/
│   ├── __init__.py
│   ├── conftest.py                 # Shared fixtures, test DB, temp dirs
│   ├── unit/
│   │   ├── domain/
│   │   ├── application/
│   │   └── infrastructure/
│   ├── integration/
│   │   ├── test_scanner.py
│   │   ├── test_metadata.py
│   │   ├── test_duplicates.py
│   │   └── test_rollback.py
│   └── fixtures/
│       ├── audio/                  # Sample audio files (generated in CI)
│       └── metadata/               # Sample MusicBrainz responses (JSON)
│
├── packaging/
│   ├── musicvault.spec             # PyInstaller spec
│   ├── installer.iss               # Inno Setup script
│   └── assets/
│       └── icon.ico
│
├── config/
│   └── defaults.json               # Default configuration template
│
├── pyproject.toml                  # Project metadata, dependencies, entry points
├── LICENSE
├── README.md
├── CHANGELOG.md
└── CONTRIBUTING.md
```

## Module Boundary Rules

| Module | May Import From | Must NOT Import From |
|--------|----------------|---------------------|
| `gui/` | `application/`, `core/`, `domain/dto` | `infrastructure/`, `plugins/builtin/` |
| `application/` | `domain/`, `core/` | `gui/`, `infrastructure/` (only via interfaces) |
| `domain/` | `core/exceptions` only | Everything else |
| `infrastructure/` | `domain/interfaces/`, `core/` | `gui/`, `application/` |
| `plugins/` | `domain/interfaces/`, `core/` | `gui/`, `application/` |

Enforced by:
- `import-linter` contracts in `pyproject.toml`
- CI check on every PR

## Naming Conventions

| Element | Convention | Example |
|---------|-----------|---------|
| Modules | `snake_case` | `scanner_service.py` |
| Classes | `PascalCase` | `ScannerService` |
| Interfaces/Protocols | `PascalCase` + suffix | `TrackRepository`, `MetadataProvider` |
| Functions | `snake_case` | `scan_library()` |
| Constants | `UPPER_SNAKE` | `MAX_THREAD_POOL_SIZE` |
| DTOs | `PascalCase` + `DTO` suffix | `TrackSummaryDTO` |
| DB tables | `snake_case` plural | `tracks`, `album_artists` |
| DB columns | `snake_case` | `file_path`, `mb_recording_id` |
| Config keys | `snake_case` | `library_paths`, `scan_options` |
| Plugin entry points | `musicvault.plugins` group | `musicbrainz = musicvault.plugins.builtin.musicbrainz` |

## Key Files Explained

### `src/musicvault/app.py`
Bootstrap sequence:
1. Initialize logging
2. Load and migrate config
3. Create DI container
4. Initialize database (create if missing, run migrations)
5. Discover and register plugins
6. Launch GUI or CLI mode

### `src/musicvault/core/container.py`
Wires all dependencies. Single place where concrete implementations are bound to interfaces. Used by both GUI and tests (with overrides for mocks).

### `src/musicvault/application/operation_orchestrator.py`
Central gate for all mutating operations. Ensures rollback snapshots, dry-run support, and transactional consistency.

### `src/musicvault/plugins/manager.py`
Discovers plugins via `importlib.metadata.entry_points`, validates against plugin protocols, manages lifecycle (load, enable, disable, configure).

## Data Directories (Runtime)

Not in the repository; created at runtime:

```
%APPDATA%/MusicVault/
├── config.json
├── secrets.json
├── musicvault.db
├── logs/
│   ├── musicvault.log
│   ├── debug.log
│   └── crashes/
├── cache/
│   ├── fingerprints/
│   ├── artwork/
│   └── musicbrainz/
├── backups/
│   └── auto/
└── rollback/
    └── snapshots/
```

## Build Artifacts

```
dist/
├── MusicVault.exe              # PyInstaller one-file or one-dir
└── MusicVault-Setup-1.0.0.exe  # Inno Setup installer
```
