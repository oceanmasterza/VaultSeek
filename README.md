# MusicVault

**Lightroom for Music** — a professional, open-source Windows application for managing large music libraries with Navidrome, Jellyfin, Plex, and self-hosted media servers.

[![Python 3.13](https://img.shields.io/badge/python-3.13-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Platform: Windows](https://img.shields.io/badge/platform-Windows-lightgrey.svg)]()

## Vision

MusicVault automates the complete lifecycle of a music library:

- **Scan** — multi-threaded ingestion of every major audio format
- **Fingerprint** — Chromaprint + AcoustID identification regardless of filename
- **Fix metadata** — MusicBrainz-driven correction with rollback
- **Organize** — configurable folder structures and intelligent renaming
- **Detect duplicates** — fingerprint, MBID, hash, and quality-aware deduplication
- **Score quality** — automatic ranking so the best copy wins
- **Manage artwork** — detect, download, embed, and report
- **Integrate** — Navidrome, Jellyfin, Plex via plugins
- **Report** — HTML, CSV, Excel, PDF exports
- **Rollback** — every operation is reversible

Designed for power users with libraries of **100,000–1,000,000+ tracks**.

## Status

**Phase 0 — Architecture** (current)

The project is in the architecture and design phase. No application code has been written yet. See [Architecture Documentation](docs/architecture/README.md) for the complete design.

## Tech Stack

| Layer | Technology |
|-------|------------|
| Language | Python 3.13 |
| GUI | PySide6 (Qt6) |
| Database | SQLite + SQLAlchemy 2.x |
| Audio metadata | Mutagen |
| Identification | MusicBrainz, AcoustID, Chromaprint |
| Fuzzy matching | RapidFuzz |
| Media processing | FFmpeg |
| Images | Pillow |
| HTTP | Requests |
| Safe delete | Send2Trash |
| Logging | Loguru |
| Testing | pytest |
| Packaging | PyInstaller |

## Architecture Principles

- **SOLID** — single responsibility, dependency inversion throughout
- **Layered architecture** — GUI → Application Services → Domain → Infrastructure
- **Plugin system** — metadata providers, artwork, media servers as plugins
- **Type safety** — full type annotations, mypy-compatible
- **Testability** — dependency injection, repository pattern, interface segregation
- **Scalability** — incremental scans, indexed queries, thread pools, caching
- **Safety** — dry-run, preview, confirmation, recycle bin, automatic backups, rollback

## Documentation

| Document | Description |
|----------|-------------|
| [Architecture Overview](docs/architecture/01-overview.md) | System design, layers, data flow |
| [Folder Layout](docs/architecture/02-folder-layout.md) | Project structure |
| [Database Schema](docs/architecture/03-database-schema.md) | Tables, indexes, relationships |
| [Service Layer](docs/architecture/04-service-layer.md) | Application and domain services |
| [Plugin API](docs/architecture/05-plugin-api.md) | Extension points and contracts |
| [GUI Architecture](docs/architecture/06-gui-architecture.md) | Qt6 MVVM presentation layer |
| [Development Roadmap](docs/architecture/07-roadmap.md) | Phased implementation plan |
| [Performance Strategy](docs/architecture/08-performance.md) | Million-track scalability |
| [Testing Strategy](docs/architecture/09-testing-strategy.md) | Unit, integration, E2E |

## Development Roadmap (Summary)

| Phase | Milestone | Status |
|-------|-----------|--------|
| 0 | Architecture & documentation | **In progress** |
| 1 | Project scaffold, DI container, config | Planned |
| 2 | Database layer & migrations | Planned |
| 3 | Domain models & repositories | Planned |
| 4 | Library scanner service | Planned |
| 5 | Fingerprint & identification engine | Planned |
| 6 | Metadata engine | Planned |
| 7 | Duplicate detection & quality scoring | Planned |
| 8 | Folder organization & rename engine | Planned |
| 9 | Artwork manager | Planned |
| 10 | Rollback engine | Planned |
| 11 | Reports | Planned |
| 12 | GUI shell & pages | Planned |
| 13 | Plugin system & Navidrome integration | Planned |
| 14 | Packaging & Windows installer | Planned |

## Getting Started (Future)

```powershell
# Clone and setup (not yet available)
git clone https://github.com/musicvault/musicvault.git
cd musicvault
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
pytest
python -m musicvault
```

## Contributing

Contributions welcome once Phase 1 scaffolding is complete. See `CONTRIBUTING.md` (coming in Phase 1).

## License

MIT License — see [LICENSE](LICENSE).
