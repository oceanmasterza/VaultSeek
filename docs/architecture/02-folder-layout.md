# 02 — Project Folder Layout (v3)

> **Updated**: Renamed layers per pipeline engine design. See [12-pipeline-engine-v3.md](12-pipeline-engine-v3.md).

## Repository Structure

```
VaultSeek/
├── .github/
│   └── workflows/
│       ├── ci.yml                  # ruff, black, mypy, pytest
│       └── release.yml             # PyInstaller on tags
│
├── docs/
│   ├── architecture/
│   ├── user-guide/
│   └── api/
│
├── src/
│   └── vaultseek/
│       ├── __init__.py
│       ├── __main__.py             # Entry point: python -m vaultseek
│       ├── app.py                  # Bootstrap: DI, logging, config, event bus
│       │
│       ├── models/                 # Pure domain (zero I/O dependencies)
│       │   ├── __init__.py
│       │   ├── entities/
│       │   │   ├── track.py
│       │   │   ├── album.py
│       │   │   ├── artist.py
│       │   │   ├── artwork.py
│       │   │   ├── job.py
│       │   │   ├── review_item.py
│       │   │   ├── rule.py
│       │   │   └── duplicate.py
│       │   ├── value_objects/
│       │   │   ├── audio_format.py
│       │   │   ├── quality_score.py
│       │   │   ├── field_confidence.py
│       │   │   ├── file_identity.py
│       │   │   ├── library_zone.py
│       │   │   └── write_dto.py
│       │   ├── services/           # Pure domain logic (no I/O)
│       │   │   ├── quality_scorer.py
│       │   │   ├── duplicate_matcher.py
│       │   │   ├── rename_engine.py
│       │   │   ├── organize_engine.py
│       │   │   └── confidence_calculator.py
│       │   └── interfaces/         # Protocol definitions
│       │       ├── repositories.py
│       │       ├── file_reader.py
│       │       ├── fingerprint.py
│       │       └── file_ops.py
│       │
│       ├── core/                   # Cross-cutting infrastructure
│       │   ├── __init__.py
│       │   ├── config.py           # JSON/YAML config load, validate, migrate
│       │   ├── container.py        # Dependency injection
│       │   ├── event_bus.py        # Thread-safe pub/sub for domain events
│       │   ├── exceptions.py
│       │   ├── logging.py          # Loguru setup
│       │   └── paths.py            # Platform app data dirs
│       │
│       ├── db/                     # SQLAlchemy Core (NOT ORM)
│       │   ├── __init__.py
│       │   ├── engine.py           # Engine factory, PRAGMA setup
│       │   ├── tables.py           # Core Table definitions
│       │   ├── uuid_utils.py       # uuid_to_blob / blob_to_uuid
│       │   ├── writer.py           # DatabaseWriter single-thread queue
│       │   ├── migrations/         # Alembic
│       │   │   ├── env.py
│       │   │   └── versions/
│       │   └── repositories/
│       │       ├── track_repo.py
│       │       ├── album_repo.py
│       │       ├── artist_repo.py
│       │       ├── job_repo.py
│       │       ├── review_repo.py
│       │       ├── rule_repo.py
│       │       ├── file_identity_repo.py
│       │       ├── duplicate_repo.py
│       │       ├── artwork_repo.py
│       │       ├── rollback_repo.py
│       │       └── change_history_repo.py
│       │
│       ├── services/               # Application / business orchestration
│       │   ├── __init__.py
│       │   ├── job_queue_manager.py
│       │   ├── job_dispatcher.py
│       │   ├── metadata_arbitrator.py
│       │   ├── review_queue_service.py
│       │   ├── rules_engine.py     # AST parser + evaluator
│       │   ├── staging_engine.py   # Zone transitions
│       │   ├── watch_folder_service.py
│       │   ├── operation_orchestrator.py
│       │   ├── rollback_service.py
│       │   ├── report_service.py
│       │   ├── plugin_controller.py
│       │   └── dto/
│       │       ├── track_dto.py
│       │       ├── job_dto.py
│       │       ├── review_dto.py
│       │       └── report_dto.py
│       │
│       ├── workers/                # Async execution (pools live here)
│       │   ├── __init__.py
│       │   ├── pools.py            # ProcessPool + ThreadPool config
│       │   ├── cpu/                # ProcessPoolExecutor workers
│       │   │   ├── hash_worker.py
│       │   │   ├── fingerprint_worker.py
│       │   │   ├── audio_parser_worker.py
│       │   │   └── quality_scorer_worker.py
│       │   └── io/                 # ThreadPoolExecutor workers
│       │       ├── scanner_worker.py
│       │       ├── metadata_worker.py
│       │       ├── artwork_worker.py
│       │       ├── duplicate_worker.py
│       │       ├── rule_worker.py
│       │       ├── organizer_worker.py
│       │       └── media_server_worker.py
│       │
│       ├── plugins/
│       │   ├── manager.py
│       │   ├── registry.py
│       │   ├── base.py
│       │   └── builtin/
│       │       ├── musicbrainz/
│       │       ├── discogs/
│       │       ├── acoustid/
│       │       ├── cover_art_archive/
│       │       ├── filename_parser/
│       │       ├── navidrome/
│       │       ├── jellyfin/
│       │       ├── plex/
│       │       ├── emby/
│       │       ├── ampache/
│       │       ├── koel/
│       │       ├── subsonic/
│       │       ├── funkwhale/
│       │       ├── lyrion/
│       │       └── mstream/
│       │
│       └── gui/
│           ├── main_window.py
│           ├── app.py              # QApplication, theme
│           ├── bridge/
│           │   └── qt_event_bridge.py  # EventBus → Qt signals
│           ├── resources/
│           ├── views/
│           ├── viewmodels/
│           └── widgets/
│
├── tests/
│   ├── conftest.py
│   ├── unit/
│   ├── integration/
│   └── fixtures/
│
├── packaging/
├── config/
│   └── defaults.json
├── pyproject.toml
├── LICENSE
├── README.md
└── CHANGELOG.md
```

## Module Boundary Rules

| Module | May Import From | Must NOT Import From |
|--------|----------------|---------------------|
| `gui/` | `services/`, `core/`, `models/`, `services/dto` | `db/`, `workers/`, `plugins/builtin/` |
| `services/` | `models/`, `core/` | `gui/`, `db/` (via interfaces only) |
| `workers/` | `models/`, `core/`, `models/interfaces` | `gui/`, `db/` (writes via WriteDTO queue only) |
| `models/` | `core/exceptions` only | Everything else |
| `db/` | `models/`, `core/` | `gui/`, `services/`, `workers/` |
| `plugins/` | `models/interfaces/`, `core/` | `gui/`, `services/` |

**Critical worker rule**: Workers never import from `db.repositories` for writes. They emit `WriteDTO` to the DB writer queue. Read-only queries are permitted through repositories.

## v2 → v3 Renames

| v2 Path | v3 Path |
|---------|---------|
| `domain/entities/` | `models/entities/` |
| `domain/value_objects/` | `models/value_objects/` |
| `domain/services/` | `models/services/` |
| `domain/interfaces/` | `models/interfaces/` |
| `application/` | `services/` |
| `application/workers/` | `workers/` |
| `infrastructure/database/` | `db/` |
| `infrastructure/audio/` etc. | `workers/` + `plugins/` (absorbed) |

## Key Files

### `db/writer.py`
Single-threaded batch writer. The only SQLite writer in the application.

### `core/event_bus.py`
Thread-safe pub/sub. Workers publish; `gui/bridge/qt_event_bridge.py` subscribes.

### `workers/pools.py`
Configures ProcessPoolExecutor (CPU) and ThreadPoolExecutor (I/O) sizes based on `os.cpu_count()`.

### `services/rules_engine.py`
Parses JSON/YAML rules into AST, evaluates against `TrackContext`.

## Runtime Data Directories

```
%APPDATA%/VaultSeek/
├── config.json
├── secrets.json
├── vaultseek.db
├── logs/
├── cache/
├── backups/
└── rollback/
```

## Library Zone Paths (on disk)

```
{library_root}/
├── Incoming/       ← watch folder
├── Staging/        ← processed, awaiting approval
├── Music/          ← canonical library
└── Archive/        ← superseded copies
```
