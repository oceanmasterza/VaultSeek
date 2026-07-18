# MusicVault

**Lightroom for Music** — a professional, open-source Windows application for managing large music libraries with self-hosted media servers.

[![Python 3.14](https://img.shields.io/badge/python-3.14-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Platform: Windows](https://img.shields.io/badge/platform-Windows-lightgrey.svg)]()

## Vision

MusicVault automates the complete lifecycle of a music library:

- **Watch folder** — drop files in Incoming/, everything else is automatic
- **Fingerprint** — Chromaprint + AcoustID identification regardless of filename
- **Multi-provider metadata** — MusicBrainz, Discogs, local tags, ranked by confidence
- **Review queue** — uncertain matches require human approval before entering the library
- **Rules engine** — configurable IF/THEN automation (archive MP3 when FLAC exists, etc.)
- **Staging library** — Incoming → Staging → Review → Library (mistakes are reversible)
- **Detect duplicates** — visual side-by-side comparison with quality scores
- **Organize & rename** — configurable folder structures, scene name cleaning
- **Media server integration** — Navidrome, Jellyfin, Plex, Emby, Ampache, Koel, and more
- **Rollback** — every operation is reversible

Designed for power users with libraries of **100,000–1,000,000+ tracks**.

## Target Users

Collectors, audiophiles, and self-hosted media server operators using **Navidrome**, **Jellyfin**, **Plex**, **Emby**, **Ampache**, **Koel**, **Subsonic**, **Funkwhale**, **Lyrion Music Server**, or **mStream**.

## Status

**Phase 16 — Packaging** (complete through 1.0.0)

Architecture is finalized (v3). The full pipeline runs end-to-end:
scan → hash → fingerprint → identify → rules → duplicates → organize →
artwork / media-server sync, with review, rollback, and reports. Phase 14
ships the Qt GUI shell and core pages; Phase 15 adds Navidrome / Jellyfin /
Plex / Subsonic rescan plugins; Phase 16 adds PyInstaller + Inno Setup
packaging with **bundled Chromaprint (`fpcalc`)** so installs are offline-
complete. See [Architecture Documentation](docs/architecture/README.md)
and [packaging/README.md](packaging/README.md).

```powershell
git clone https://github.com/oceanmasterza/MusicVault.git
cd MusicVault
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
pytest              # full suite
python -m musicvault  # launches GUI
# CI / automation: python -m musicvault --headless
```

## Tech Stack

| Layer | Technology |
|-------|------------|
| Language | Python 3.14 |
| GUI | PySide6 (Qt6) |
| Database | SQLite + **SQLAlchemy Core** (not ORM) |
| Identities | **UUID v7** (all entities) |
| Processing | **Persistent job queue** with independent workers |
| Audio metadata | Mutagen |
| Identification | MusicBrainz, Discogs, AcoustID, Chromaprint |
| Fuzzy matching | RapidFuzz |
| Media processing | FFmpeg |
| Logging | Loguru |
| Testing | pytest + mypy strict |
| CI | GitHub Actions (ruff, black, mypy, pytest) |
| Packaging | PyInstaller |

## Architecture Highlights (v3)

| Decision | Choice | Why |
|----------|--------|-----|
| Database access | SQLAlchemy Core | 3–5× faster than ORM at 1M+ rows |
| Writes | Single-writer DB thread | Eliminates SQLite lock contention |
| CPU-bound work | ProcessPool | Bypasses the GIL for hashing/fingerprinting |
| Processing | Job queue + workers | Resumable, crash-safe, observable |
| Metadata | Multi-provider arbitration | No single source of truth |
| Uncertain data | Review queue (< 90% confidence) | Prevents metadata corruption |
| File placement | Staging library | Mistakes don't touch canonical library |
| Automation | Rules engine + watch folder | Zero-click processing |
| CI | From Phase 1 | No broken commits from day one |

## Documentation

| Document | Description |
|----------|-------------|
| **[Pipeline Engine v3](docs/architecture/12-pipeline-engine-v3.md)** | Latest — DB writer, ProcessPool, event bus |
| [Revision v2](docs/architecture/10-revision-v2.md) | Job queue, UUID, review, staging |
| [Overview](docs/architecture/01-overview.md) | Job pipeline, library zones |
| [Folder Layout](docs/architecture/02-folder-layout.md) | `models/`, `core/`, `db/`, `services/`, `workers/` |
| [Database Schema](docs/architecture/03-database-schema.md) | UUID schema, jobs, review queue |
| [Service Layer](docs/architecture/04-service-layer.md) | Job queue, arbitrator, rules |
| [Plugin API](docs/architecture/05-plugin-api.md) | 10 media servers |
| [Roadmap](docs/architecture/07-roadmap.md) | 16-phase plan |
| [CI Pipeline](docs/architecture/11-ci-pipeline.md) | GitHub Actions spec |

## Development Roadmap (Summary)

| Phase | Milestone | Status |
|-------|-----------|--------|
| 0 | Architecture v1 | Complete |
| 0b | Architecture v2 revision | Complete |
| 1 | Scaffold + CI | Complete |
| 2 | Database Layer | Complete |
| 3 | Domain Models | Complete |
| 4 | Job Dispatcher + Scanner/Hash Workers | Complete |
| 5 | Fingerprint Worker | Complete |
| 6 | Metadata Arbitrator + Providers | Complete |
| 7 | Review Queue | Complete |
| 8 | Rules Engine | Complete |
| 9 | Duplicate Detection | Complete |
| 10 | Organizer + Watch Folder | Complete |
| 11 | Artwork Worker | Complete |
| 12 | Rollback Engine | Complete |
| **13** | **Reports** | **Current** |
| 14–16 | GUI → Plugins → Installer | Planned |

## License

MIT License — see [LICENSE](LICENSE).
