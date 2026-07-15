# MusicVault

**Lightroom for Music** — a professional, open-source Windows application for managing large music libraries with self-hosted media servers.

[![Python 3.13](https://img.shields.io/badge/python-3.13-blue.svg)](https://www.python.org/downloads/)
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

**Phase 0b — Architecture v2** (current)

Architecture revision complete. No application code yet. See [Architecture Documentation](docs/architecture/README.md).

## Tech Stack

| Layer | Technology |
|-------|------------|
| Language | Python 3.13 |
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

## Architecture Highlights (v2)

| Decision | Choice | Why |
|----------|--------|-----|
| Database access | SQLAlchemy Core | 3–5× faster than ORM at 1M+ rows |
| Processing | Job queue + workers | Resumable, crash-safe, observable |
| Metadata | Multi-provider arbitration | No single source of truth |
| Uncertain data | Review queue (< 90% confidence) | Prevents metadata corruption |
| File placement | Staging library | Mistakes don't touch canonical library |
| Automation | Rules engine + watch folder | Zero-click processing |
| CI | From Phase 1 | No broken commits from day one |

## Documentation

| Document | Description |
|----------|-------------|
| **[Architecture v2](docs/architecture/10-revision-v2.md)** | Master revision with scalability review |
| [Overview](docs/architecture/01-overview.md) | Job pipeline, library zones |
| [Database Schema](docs/architecture/03-database-schema.md) | UUID schema, jobs, review queue |
| [Service Layer](docs/architecture/04-service-layer.md) | Job queue, arbitrator, rules |
| [Plugin API](docs/architecture/05-plugin-api.md) | 10 media servers |
| [Roadmap](docs/architecture/07-roadmap.md) | 16-phase plan |
| [CI Pipeline](docs/architecture/11-ci-pipeline.md) | GitHub Actions spec |

## Development Roadmap (Summary)

| Phase | Milestone | Status |
|-------|-----------|--------|
| 0 | Architecture v1 | Complete |
| **0b** | **Architecture v2 revision** | **Current** |
| 1 | Scaffold + CI | Next |
| 2–16 | Database → GUI → Plugins → Installer | Planned |

## License

MIT License — see [LICENSE](LICENSE).
