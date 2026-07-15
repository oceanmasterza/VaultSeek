# MusicVault Architecture Documentation

This directory contains the complete software architecture for MusicVault, designed before any application code is written.

## Documents

| # | Document | Purpose |
|---|----------|---------|
| 01 | [Overview](01-overview.md) | System context, layered architecture, data flows |
| 02 | [Folder Layout](02-folder-layout.md) | Repository structure and module boundaries |
| 03 | [Database Schema](03-database-schema.md) | SQLite tables, indexes, migrations |
| 04 | [Service Layer](04-service-layer.md) | Application services, domain logic, interfaces |
| 05 | [Plugin API](05-plugin-api.md) | Plugin contracts, lifecycle, built-in plugins |
| 06 | [GUI Architecture](06-gui-architecture.md) | MVVM, views, view models, threading |
| 07 | [Roadmap](07-roadmap.md) | Phased implementation plan with acceptance criteria |
| 08 | [Performance](08-performance.md) | Scalability for 1M+ tracks |
| 09 | [Testing Strategy](09-testing-strategy.md) | Test pyramid, fixtures, CI |

## Design Goals

1. **Production quality** — not a script; designed for hundreds of contributors
2. **Separation of concerns** — GUI, application logic, domain, infrastructure are isolated
3. **Plugin-first** — metadata providers, artwork, media servers are plugins from day one
4. **Reversible operations** — every mutating action is logged and rollback-capable
5. **Scale** — comfortable with 1,000,000+ tracks via incremental scans and indexed storage
6. **Type safety** — full annotations, dataclasses, mypy strict mode

## Key Architectural Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| GUI framework | PySide6 (Qt6) | Native Windows look, mature widget set, signals/slots, dark mode |
| Database | SQLite + SQLAlchemy 2.x | Embedded, zero-config, WAL mode for concurrency, proven at scale |
| DI container | `dependency-injector` or manual constructor injection | Testability without framework magic |
| Async model | Thread pools + Qt signals (not asyncio in GUI) | Qt is not asyncio-native; CPU-bound work in threads |
| Plugin loading | Entry points (`pyproject.toml`) + runtime discovery | Standard Python packaging, hot-reload in dev |
| Config format | Versioned JSON with migration chain | Human-readable, diffable, auto-upgraded |
| File safety | Send2Trash + pre-operation snapshots | Never hard-delete; always recoverable |

## Layer Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    Presentation (GUI)                        │
│  PySide6 Views  ←→  ViewModels  ←→  Application Facade      │
├─────────────────────────────────────────────────────────────┤
│                    Application Layer                         │
│  ScannerService  MetadataService  DuplicateService  ...      │
│  OperationOrchestrator  RollbackService  ReportService       │
├─────────────────────────────────────────────────────────────┤
│                    Domain Layer                                │
│  Entities  Value Objects  Domain Services  Specifications    │
├─────────────────────────────────────────────────────────────┤
│                    Infrastructure Layer                      │
│  SQLAlchemy Repos  FileSystem  FFmpeg  Chromaprint  HTTP    │
├─────────────────────────────────────────────────────────────┤
│                    Plugin Layer                              │
│  MusicBrainz  AcoustID  Navidrome  ArtworkProviders  ...   │
└─────────────────────────────────────────────────────────────┘
```

## Reading Order

For new contributors, read documents 01 → 07 in order. Documents 08 and 09 are reference material consulted during implementation of their respective phases.
