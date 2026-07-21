# VaultSeek Roadmap

Public-facing roadmap for GitHub visitors. For day-to-day engineering progress, see [DEVELOPMENT_ROADMAP.md](DEVELOPMENT_ROADMAP.md) (internal AI development notebook).

**Last updated:** 2026-07-21

---

## Phase 1 — Foundation

**Status: Complete**

- Fork MusicVault into VaultSeek (separate app, separate data directory)
- Rebrand package and installer (`vaultseek`, `%APPDATA%\VaultSeek`)
- Preserve working library pipeline (scan → identify → organize → artwork → media server)
- Planning docs, ADRs, CI, 570+ tests
- GitHub repository: [oceanmasterza/VaultSeek](https://github.com/oceanmasterza/VaultSeek)

---

## Phase 2 — Acquisition foundation

**Status: Complete**

- `AcquisitionJob` entity + deterministic state machine
- `AcquisitionEngine` with SQLite persistence (`acquisition_jobs` table)
- `MissingMediaAnalyzer` — gap detection vs MusicBrainz release tracklists
- Automatic `AcquisitionJob` creation for missing tracks
- `AcquisitionProvider` protocol, `ProviderManager`, stub provider

---

## Phase 3 — Provider configuration

**Status: Complete**

- `AcquisitionConfig` (schema v9) — enabled providers, order, auto-acquire threshold, Nicotine+ settings
- Bootstrap-time provider connect from `config.json`

---

## Phase 4 — Nicotine+ integration

**Status: HTTP adapter + UI wiring**

First real acquisition provider — communicates with an installed Nicotine+ client (not raw Soulseek protocol). Nicotine+ has no official RPC; VaultSeek uses a documented NDJSON socket protocol or the community HTTP API.

- Connection probe and graceful failure when Nicotine+ is offline ✅
- `NicotinePlusRpcClient` + `FakeRpcClient` + `LocalSocketRpcClient` ✅
- `HttpApiRpcClient` for api-nicotine-plus ✅
- NDJSON socket companion via proxy script ✅
- Completion hand-off to Verification Pipeline ✅

Nicotine+ is the **first** provider, not the architecture.

---

## Phase 5 — Acquisition Engine subsystems

**Status: Wired (verify/import beyond stubs)**

| Subsystem | Status |
|-----------|--------|
| Missing Media Analyzer | ✅ |
| Search Dispatcher | ✅ skeleton |
| Scoring Engine | ✅ skeleton |
| Download Manager | ✅ skeleton |
| Verification Engine | ✅ path / tags / hash / fingerprint checks |
| Import Pipeline | ✅ Incoming stage + scan enqueue (organize/artwork via existing pipeline) |
| Acquisition UI | ✅ wishlist + progress page |
| Auto-acquire threshold | ✅ configurable (default 90%) |

User-facing: result picker, background scheduled automation, and retry/history UI — wired ✅

---

## Phase 6 — Automation

**Status: Core wired**

- Minimal-intervention workflows (“detect missing album → acquire → verify → import”) ✅
- Background auto-acquire + download polling (`AcquisitionAutomationService`) ✅
- Failed-job retry policies with exponential backoff ✅
- Scheduled re-scans for library completeness (partial — missing-media scan manual)
- Media server refresh after import (deferred until import requests it)
- Processing reports and richer acquisition history UI (partial — last-note column in UI)

---

## Longevity

- Shared `MusicVault.Core` extraction (library models, organize, plugins)
- Additional providers beyond Nicotine+
- Cross-platform only after Windows desktop maturity
