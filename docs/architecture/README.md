# VaultSeek Architecture Documentation

Complete software architecture for VaultSeek. Implementation has caught up
with Phases 1–16 (pipeline, GUI browse pages, media servers, Windows Setup).

> **Current version**: v3. Start with [12-pipeline-engine-v3.md](12-pipeline-engine-v3.md).
> Post-MVP polish (plugin manager UI, Discogs, report viewer) is tracked in
> [07-roadmap.md](07-roadmap.md) Phase 14 deferred notes.

## Documents

| # | Document | Purpose |
|---|----------|---------|
| **12** | **[Pipeline Engine v3](12-pipeline-engine-v3.md)** | **Latest — start here** |
| **10** | [Revision v2](10-revision-v2.md) | Job queue, UUID, review, staging |
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
| 12 | **[Pipeline Engine v3](12-pipeline-engine-v3.md)** | DB writer queue, ProcessPool, event bus |

## v3 Key Changes (from v2)

| Change | Impact |
|--------|--------|
| **Single-writer DB queue** | Eliminates SQLite lock contention at scale |
| **ProcessPool** for CPU workers | Bypasses GIL; multi-core hash/fingerprint |
| **Event bus** + Qt bridge | GUI never coupled to worker threads |
| **UUID as BLOB(16)** | ~20 MB index savings per column at 1M rows |
| **Batch writes 5K–10K** | Optimal transaction size for single writer |
| **Folder rename** | models/, services/, db/, workers/ |
| **Composite confidence** | Weighted match score for review routing |
| **Rules AST** | JSON/YAML → parsed tree evaluation |

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
│                    GUI (PySide6) + Event Bus Bridge          │
├─────────────────────────────────────────────────────────────┤
│                    Services Layer                            │
│  JobQueue │ Arbitrator │ Review │ Rules │ Staging │ Rollback│
├──────────────────────────┬──────────────────────────────────┤
│  ProcessPool (CPU)       │  ThreadPool (I/O)                │
│  Hash │ Fingerprint │ Parse│  Scan │ Metadata │ Organize │ … │
├──────────────────────────┴──────────────────────────────────┤
│              Database Writer Queue (single thread)           │
├─────────────────────────────────────────────────────────────┤
│  Models (UUID dataclasses) │ DB (SQLAlchemy Core) │ Plugins │
└─────────────────────────────────────────────────────────────┘
```

## Reading Order

1. **[12-pipeline-engine-v3.md](12-pipeline-engine-v3.md)** — latest refinements (DB writer, ProcessPool, event bus)
2. **[10-revision-v2.md](10-revision-v2.md)** — v2 design decisions + scalability review
3. **01 → 07** — detailed specifications
4. **08, 09, 11** — reference during implementation
