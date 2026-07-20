# VaultSeek Roadmap

Public-facing roadmap for GitHub visitors. For day-to-day engineering progress, see [DEVELOPMENT_ROADMAP.md](DEVELOPMENT_ROADMAP.md) (internal AI development notebook).

**Last updated:** 2026-07-20

---

## Phase 1 — Foundation

**Status: Complete**

- Fork MusicVault into VaultSeek (separate app, separate data directory)
- Rebrand package and installer (`vaultseek`, `%APPDATA%\VaultSeek`)
- Preserve working library pipeline (scan → identify → organize → artwork → media server)
- Planning docs, ADRs, CI, 550+ tests
- GitHub repository: [oceanmasterza/VaultSeek](https://github.com/oceanmasterza/VaultSeek)

---

## Phase 2 — Provider Framework

**Status: In progress (skeleton complete)**

- `AcquisitionProvider` protocol and normalized `SearchRequest` / `SearchResult` types
- `ProviderManager` — sole gateway to external acquisition sources
- Stub provider for wiring and tests
- `AcquisitionJob` entity + deterministic state machine
- `AcquisitionEngine` skeleton (in-memory)

**Next:** persist jobs, provider configuration UI, provider discovery.

---

## Phase 3 — Nicotine+ integration

**Status: Planned**

First real acquisition provider — communicates with an installed Nicotine+ client (not raw Soulseek protocol).

- Connection and availability detection
- Search dispatch and async result collection
- Download queue and progress
- Completion hand-off to Verification Pipeline

Nicotine+ is the **first** provider, not the architecture.

---

## Phase 4 — Acquisition Engine

**Status: Planned (design complete, implementation starting)**

Full Acquisition Engine subsystems per [ARCHITECTURAL_UPDATE_001.md](ARCHITECTURAL_UPDATE_001.md):

| Subsystem | Purpose |
|-----------|---------|
| Missing Media Analyzer | Gap detection vs MusicBrainz / library |
| Acquisition Job Scheduler | Queue and priority |
| Search Dispatcher | Provider-independent search requests |
| Result Collector | Timeouts, cancellation, aggregation |
| Scoring Engine | Weighted confidence, best-match selection |
| Download Manager | Retries, history, concurrency |
| Verification Engine | Mandatory pre-import checks |
| Import Pipeline | Reuse MusicVault organize / artwork / duplicates |

User-facing: wishlist, confidence %, auto-acquire above threshold (e.g. 90%).

---

## Phase 5 — Automation

**Status: Planned**

- Minimal-intervention workflows (“detect missing album → acquire → verify → import”)
- Scheduled re-scans for library completeness
- Failed-job retry policies
- Media server refresh after import
- Processing reports and acquisition history UI

---

## Future vision

- **Multiple providers** in parallel (Nicotine+, local archive, Lidarr, …)
- **Quality upgrades** — FLAC replacement jobs as first-class `AcquisitionJob` type
- **Library optimisation** — completeness dashboard, duplicate replacement suggestions
- **Intelligent acquisition** — learning preferred releases, scoring profiles
- **Plugin ecosystem** — installable providers without core changes
- **Shared core** — `MusicVault.Core` package consumed by both apps

---

## How to follow progress

- **Issues & board:** [GitHub Projects](https://github.com/users/oceanmasterza/projects) (VaultSeek board)
- **CI:** [![CI](https://github.com/oceanmasterza/VaultSeek/actions/workflows/ci.yml/badge.svg)](https://github.com/oceanmasterza/VaultSeek/actions/workflows/ci.yml)
- **Contributing:** [CONTRIBUTING.md](../CONTRIBUTING.md)
