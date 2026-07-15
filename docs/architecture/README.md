# MusicVault Architecture Documentation

Complete software architecture for MusicVault — designed before application code is written.

> **Current version**: v2 (2026-07-15). Start with [10-revision-v2.md](10-revision-v2.md).

## Documents

| # | Document | Purpose |
|---|----------|---------|
| **10** | **[Revision v2](10-revision-v2.md)** | **Master revision — start here** |
| 01 | [Overview](01-overview.md) | System design, job pipeline, library zones |
| 02 | [Folder Layout](02-folder-layout.md) | Project structure |
| 03 | [Database Schema](03-database-schema.md) | UUID schema, jobs, review, staging |
| 04 | [Service Layer](04-service-layer.md) | Job queue, arbitrator, rules engine |
| 05 | [Plugin API](05-plugin-api.md) | 10 media servers, metadata ranking |
| 06 | [GUI Architecture](06-gui-architecture.md) | Review queue, duplicate viewer, jobs |
| 07 | [Roadmap](07-roadmap.md) | 16-phase implementation plan |
| 08 | [Performance](08-performance.md) | Million-track scalability |
| 09 | [Testing Strategy](09-testing-strategy.md) | Test pyramid, fixtures |
| 11 | [CI Pipeline](11-ci-pipeline.md) | GitHub Actions from Phase 1 |

## v2 Key Changes (from v1)

| Change | Impact |
|--------|--------|
| SQLAlchemy **Core** (not ORM) | 3–5× faster bulk inserts |
| **UUID v7** primary keys | Import/export, plugin sync safe |
| **Job queue** + independent workers | Resumable, crash-safe pipeline |
| **Metadata arbitration** with confidence | Multi-provider, per-field ranking |
| **Review queue** | Human gate for confidence < 90% |
| **Staging library** | Incoming → Staging → Review → Library |
| **Rules engine** | User-configurable IF/THEN automation |
| **Watch folder** | Zero-click incoming pipeline |
| **10 media server plugins** | Navidrome DB access, Jellyfin, Plex, … |
| **CI from Phase 1** | ruff, black, mypy, pytest on every commit |

## Design Goals

1. Production quality — designed for hundreds of contributors
2. Job-driven processing — everything async, resumable, observable
3. Human-in-the-loop — review queue prevents metadata corruption
4. Plugin-first — metadata, artwork, media servers as plugins
5. Reversible — rollback snapshots for every mutation
6. Scale — 1,000,000+ tracks via Core SQL, job queue, fingerprint caching

## Layer Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    Presentation (GUI)                        │
│  Views ←→ ViewModels ←→ Application Services                 │
├─────────────────────────────────────────────────────────────┤
│                    Application Layer                         │
│  JobQueueService │ MetadataArbitrator │ ReviewQueueService   │
│  RulesEngine │ OperationOrchestrator │ WatchFolderService   │
├─────────────────────────────────────────────────────────────┤
│                    Workers (Job Handlers)                    │
│  Scanner │ Hash │ Fingerprint │ Metadata │ Artwork │ ...    │
├─────────────────────────────────────────────────────────────┤
│                    Domain Layer                              │
│  Entities (UUID) │ Value Objects │ Domain Services           │
├─────────────────────────────────────────────────────────────┤
│                    Infrastructure                            │
│  Repositories (SQLAlchemy Core) │ FileSystem │ HTTP         │
├─────────────────────────────────────────────────────────────┤
│                    Plugin Layer                              │
│  MusicBrainz │ Discogs │ Navidrome │ Jellyfin │ Plex │ ... │
└─────────────────────────────────────────────────────────────┘
```

## Reading Order

1. **[10-revision-v2.md](10-revision-v2.md)** — scalability review + all design decisions
2. **01 → 07** — detailed specifications
3. **08, 09, 11** — reference during implementation
