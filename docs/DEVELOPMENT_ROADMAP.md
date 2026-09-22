# DEVELOPMENT_ROADMAP.md

# VaultSeek Development Roadmap

Version: 1.1

Status: Active development

Overall Progress: 48%

---

# Purpose

This document acts as the project's persistent engineering notebook.

Unlike PROJECT_PLAN.md and ARCHITECTURE.md, which define long-term design decisions, this document tracks implementation progress.

Every AI coding session should begin by reading this file.

Also read ARCHITECTURAL_UPDATE_001.md (Acquisition Engine / AcquisitionJob).

Update this document whenever major milestones are completed.

---

# Current Project Status

Project State

🟢 Active

Current Phase

Phase 6 automation + polish (reports, dashboard acquisition summary)

Current Sprint

Sprint 4

Current Goal

Keep `gitlab/main` as the shared AI branch. Settings vs Plugins ownership and
search waterfall must stay merged; next work is live provider testing after
the user adds plugin credentials.
---

# Vision Statement

MusicVault manages an existing music library.

VaultSeek discovers and acquires missing music.

The two applications should eventually share a common reusable core while remaining independent applications.

---

# Guiding Principles

Every architectural decision should support:

Modularity

Extensibility

Maintainability

Testability

AI-assisted development

Provider independence

Code clarity

Long-term sustainability

---

# Architecture Decisions (DO NOT CHANGE WITHOUT REVIEW)

Decision #001

VaultSeek uses a Provider Framework.

Approved

Reason

Allows multiple download providers without changing the application core.

---

Decision #002

The first provider is Nicotine+.

Approved

Reason

Leverages an existing mature implementation instead of immediately implementing the Soulseek protocol.

---

Decision #003

Search generation is provider-independent.

Approved

Providers translate SearchRequests into provider-specific implementations.

---

Decision #004

Downloaded files are always verified before import.

Approved

Verification is mandatory.

---

Decision #005

Business logic belongs in Services.

Approved

ViewModels remain presentation-only.

---

Decision #006

Everything should be asynchronous.

Approved

Never block the UI thread.

---

Decision #007

Dependency Injection is required.

Approved

Avoid direct instantiation of services.

---

Decision #008

SOLID principles are mandatory.

Approved

---

Decision #009

Composition is preferred over inheritance.

Approved

---

Decision #010

AI readability takes precedence over code cleverness.

Approved

---

# Project Phases

## Phase 1

Repository Preparation

Status

✅ Complete (2026-07-20)

Tasks

Rename solution ✅

Rename projects ✅

Rename namespaces ✅

Update branding ✅

Compile successfully ✅

Run existing tests ✅

Deliverable

VaultSeek builds; separate `%APPDATA%\VaultSeek` data dir.

---

## Phase 2

Core Refactoring / Acquisition foundation

Status

✅ Complete

Tasks

AcquisitionJob entity + state machine ✅

AcquisitionEngine skeleton ✅

Provider Framework stub ✅

Import ARCHITECTURAL_UPDATE_001 ✅

Persist AcquisitionJob (DB) ✅

Missing Media Analyzer ✅

AcquisitionJob creation from gaps ✅

Deliverable

Stable persisted AcquisitionJob API; Missing Media Analyzer creates jobs for missing tracks.

---

## Phase 3

Provider Framework

Status

✅ Complete

Tasks

Create Provider interfaces ✅

Create Provider Manager ✅

Provider registration ✅

Configuration ✅ (`AcquisitionConfig` schema v8)

Plugin loading ✅

Dependency Injection ✅

Deliverable

Application supports multiple providers via config + ProviderManager.

---

## Phase 4

Nicotine+ Provider

Status

🟡 Skeleton complete (no live search/download yet)

Tasks

Connection ✅ (TCP probe)

Availability detection ✅

Authentication (if required) — deferred

Search — stub (empty until RPC client)

Receive results — deferred

Queue downloads — stub handle

Monitor progress — stub status

Completion detection — deferred

Deliverable

Graceful connect without Nicotine+; live search/download still planned.

---

## Phase 5

Missing Media Detection

Status

✅ Complete (analyzer + job creation; quality comparison deferred)

Tasks

Album analysis ✅

Track analysis ✅

Incomplete release detection ✅

Quality comparison — deferred

Deliverable

Accurate missing-media identification vs MusicBrainz tracklists.

---

## Phase 6

Search Dispatcher (Acquisition Engine)

Status

✅ Complete (skeleton)

Tasks

Generate SearchRequests ✅

Provider dispatch ✅

Timeout handling ✅ (config field; sync dispatch for now)

Cancellation — via job cancel

Deliverable

Provider-independent searching.

---

## Phase 7

Scoring Engine

Status

✅ Complete (skeleton)

Tasks

Normalize results ✅

Weighted scoring ✅

Recommendation engine ✅ (`select_best`)

Configurable priorities ✅ (`ScoringWeights`)

Deliverable

Automatic best-match selection (heuristic weights).

---

## Phase 8

Download Manager

Status

🟡 Skeleton complete

Tasks

Queue ✅ (in-memory handles)

Retries — deferred

Resume — deferred

Cancellation ✅

History — deferred

Progress — via provider status

Deliverable

Download orchestration via ProviderManager (full retries later).

---

Reliable download workflow.

---

## Phase 9

Verification Engine

Status

🟡 Skeleton complete

Tasks

Fingerprint — deferred (stub note)
Metadata validation — path/filename hints ✅
Duplicate detection — stub ✅
Release verification — mb_release_id presence ✅

Deliverable

Safe automatic importing.

---

## Phase 10

Import Pipeline

Status

🟡 Skeleton complete (wiring stubs)

Tasks

Artwork — stub ✅
Organisation — stub ✅
Metadata — stub ✅
Library updates — stub ✅
Media server refresh — stub ✅

Deliverable

Downloaded albums appear automatically inside the library.

---

## Phase 11

UI

Status

⬜ Not Started

Tasks

Provider management

Search progress

Recommendations

Download queue

History

Settings

Deliverable

Complete user experience.

---

# Current Sprint

Sprint

Sprint 1

Goal

Rename MusicVault to VaultSeek.

Expected Deliverables

Working solution

Updated namespaces

Updated branding

No regressions

No new functionality

---

# Next Five Tasks

1.

Fork MusicVault repository.

Priority

High

---

2.

Rename solution.

Priority

High

---

3.

Rename projects.

Priority

High

---

4.

Compile successfully.

Priority

Critical

---

5.

Create Provider Framework skeleton.

Priority

High

---

# Backlog

Native Soulseek Provider

Multiple provider support

Parallel provider searching

Provider prioritisation

Automatic quality upgrades

Wishlist support

Scheduled searches

Automatic retry of failed albums

Metadata repair

Cross-provider result comparison

Cloud providers

Remote libraries

MusicBrainz release preferences

Discogs release scoring

User scoring profiles

Dark mode improvements

---

# Technical Debt

Current

None

Future

Track all shortcuts here.

Every shortcut should include:

Reason

Impact

Suggested fix

Priority

---

# Known Issues

None

---

# Future Enhancements

Machine-learning result ranking

Learning user preferences

Automatic preferred release selection

Release history

Acquisition analytics

Provider health monitoring

Plugin marketplace

Distributed searching

Metadata confidence scoring

Automatic duplicate replacement

Quality upgrade suggestions

Library completeness dashboard

---

# Risks

Nicotine+ communication changes.

Provider API changes.

Soulseek protocol evolution.

Metadata inconsistencies.

Incorrect release matching.

Duplicate downloads.

Large library performance.

Mitigation

Keep provider abstraction clean.

---

# Performance Goals

Application startup

<2 seconds

Library scan

Comparable to MusicVault

Search response

<5 seconds (provider dependent)

UI responsiveness

Never blocked

Background work

Always asynchronous

---

# Testing Goals

Unit test all Services.

Integration test Providers.

Mock external systems.

Automated regression tests.

Manual end-to-end workflow verification.

---

# Success Metrics

Successful search rate

Successful import rate

Duplicate detection accuracy

Metadata match accuracy

Download completion rate

Library integrity

---

# Session Notes

## 2026-09-22 — Delivery resume (scoped Salvation seven)

- Codex restored gate after independent scoped clone: AUTO 7, organized 7, FLAC QUALITY_UPGRADE 7.
- Live apply: exact seven → canonical Salvation `019f907c-a63b-7000-9a20-d1bb17bd3381`; tags Alphaville/Salvation; collision-safe `(1)` names when library slot occupied; config SHA unchanged.
- Seven QUALITY_UPGRADE jobs created (prefer_lossless) and **queued only** (no delivery downloads claimed).
- Packaging: dated `VaultSeek-Setup-20260922.exe`; smoke onedir/disposable/installed with Review seed profile.

## 2026-09-22 — Provenance-final (early identify seed)

Acquisition folder provenance now fills absent artist/album on the identify
query after embedded tags and before MusicBrainz/Discogs tag search. Never
inherits the acquisition job title; never overrides contradictory embedded
artist. Library matcher still reuses the same provenance snapshot at step 4b.
Named radio/single-edit variants remain incompatible with bare studio.
`tag_writer` untouched. No build/commit.

## 2026-09-22 — Workflow gates final (Codex review)

Seven review gates closed: physical better-slot evidence; live Container
config for scoped QUALITY_UPGRADE; retryable upgrade-job dedupe; public
`recording_identity` blocks contradictory upgrade hits (no track_count
bypass; band Live safe); fail-closed injected tag writer; LIBRARY same-zone
reorganize on Assign; organize reports `quality_upgrade_error`. Full unit
suite 921 passed. Isolated clone E2E (SQLite API backup, temp media only):
AUTO 7 → Salvation, tags + organize + seven QUALITY_UPGRADE jobs. No live
mutation, commit, push, or build.

## 2026-09-22 — Identify workflow final (identity ≠ quality)

Library tracklist matching now separates identity from quality: a better
active LIBRARY copy does not block unique auto-identify; after tags, worse
Incoming archives via organize/duplicate. Exact provenance release MBID
outranks other editions. Slot identity keys keep full version text so
studio/demo copies never Frankenstein-merge evidence. Provenance resolves
completed same-library `nicotine_download_folder` / `local_paths` only.
ReviewQueueService exports `AlbumChoice` / `AlbumSlotChoice` plus
`assignment_albums` / `assignment_slots`. `apply_safe_matches` reports
per-row applied/failed and continues the batch. Scoped QUALITY_UPGRADE with
`source_track_id` runs from OrganizerWorker after LIBRARY placement.
Read-only live preview of the seven Salvation Incoming songs: AUTO 7 / STAY 0,
all predicted album **Salvation** (not Deluxe). No live mutation, config,
commit, or build in this session.

## 2026-09-22 — Identify / Review album allocation

Filename parser skips Nicotine UUID parents and parses `NN - Title`. Library
tracklist matcher recommends album slots using filename/title, acquisition
folder provenance (artist/album/MBID only — never job title), duration, and
track number. Unique auto-approve requires ≥2 corroborations with ≥1 song-side
evidence; title-only, version/edition conflicts, release MBID mismatch, and
better existing files stay in Review. Review UI Assign album / Apply writes
tags (backup + atomic replace), clears artwork_missing blockers, enqueues
artwork + hash refresh. Quality-upgrade scans dedupe open jobs. No live DB
mutations or config changes in this session; safe retry remains dry-run until
Codex authorizes backups + apply.

## 2026-09-21 — Refused download start stays on the legal path

Startup polling of a Nicotine+ download whose client is disconnected tries the next scored peer. That start used to advance `scoring -> download_failed` and abort the library tick, leaving the job in `scoring`. `DownloadManager` now records the refusal as `scoring -> downloading -> download_failed`. The direct transition stays illegal. A later connected waterfall tier can still start, and a verification failure can still try the next result.

Delivery used that build. Prior checks: 867 unit tests passed, plus the 22 acquisition regressions. Installer `packaging/output/VaultSeek-Setup.exe` SHA256 `7C649832C4A0720E2E74679B3078F72C34032FD09D0870C2922A7D11A21FBD83`. Frozen and installed `VaultSeek.exe` SHA256 `28D08A706D7CA8874BF3FD202C96FC2ECF20A25D236B51C33C53B7882B591262`. Dated copy: `packaging/output/VaultSeek-Setup-20260921-final.exe`. Inno exit 0 over the per-user Programs folder. Config SHA256 stayed `5628CA5E9475965DADD1032A5B46CE5E1D3AB3CEDFAB280D54D8F429A35FE76A`. The SQLite backup-API snapshot matched before and after (`completed:138; downloading:5; queued:294; searching:2; verification_failed:2`). Isolated temporary AppData smoke saw window title VaultSeek, WM_NULL at 1280 and 720, pipeline Discover/Hash/Sync with a narrow wrap, Albums Archive/Delete/Find music, and Settings Save library/Save preferences. No traceback or crash file. The real profile was not launched.

## 2026-09-21 — Combined Albums, pipeline, and advanced settings

Albums owns covers. Artwork is not its own sidebar page; older Artwork links open Albums with Problems only. Cover identity is provenance-first: a trusted `artwork.source_id` matching the album MBID may claim the cover, foreign provenance blocks the wrong album, and popularity counts or timestamps do not pick a winner. Numbered slots include the normalized title so Live, Acoustic, and Remix editions stay distinct.

The dashboard pipeline and toolbars use shared flow layout, so Discover, Hash, Sync, and the later stages stay fully visible and wrap when the window is narrow. Settings and Plugins still expose the advanced controls from `7125ee7` (folders, quality, wishlist and waterfall, Nicotine+, AcoustID, pipeline workers, media servers, and download clients). Reconnect runs off the UI thread on one provider lifecycle lock. Unsaved library and media edits confirm before discard. Numeric fields refit without a `rangeChanged` handler.

Provider status for the dashboard reads immutable connected and order snapshots, so a search delay or reconnect cannot freeze the window.

Validation before install: 862 unit tests passed; ruff clean; strict mypy on 248 files; import-linter kept 3 contracts; Black unchanged on 32 changed Python files. Independent review approved those checks and the hashes below. Installer `packaging/output/VaultSeek-Setup.exe` SHA256 `C6A073A0D1876C5F76962A7550901BA454360ED0D91678CC45C8F5F307E0CED0`. Frozen and installed `VaultSeek.exe` SHA256 `6483088858E4D762688B8FC8B59D2D876995C79083DF2FDA73A5A3F02D0469B4`. Dated handoff copy: `packaging/output/VaultSeek-Setup-20260921.exe`.

Real upgrade on 2026-09-21: Inno exit 0 over the existing per-user Programs folder. Config SHA256 stayed `5628CA5E9475965DADD1032A5B46CE5E1D3AB3CEDFAB280D54D8F429A35FE76A`. Obsolete ICU DLLs are absent. The real-profile main window titled VaultSeek answered WM_NULL with Responding true and closed without using Archive, Delete, Find, or Scan. Incoming, library, and archive file fingerprints were unchanged. Startup automation logged an illegal `scoring -> download_failed` transition and moved one acquisition job; that database was restored from the pre-launch SQLite backup so job counts match the pre-test profile.

## 2026-09-21 — Provider status snapshots (release-final)

Dashboard/`ProviderManager` status no longer acquires the lifecycle RLock held
during search waterfall sleeps or background reconnect. Connected ids and search
readiness come from immutable snapshots published after mutations. Unit tests
prove status returns while search and reconnect are blocked. Packaging/smoke
evidence in the release-final agent report.

## 2026-09-20 — Responsive FlowLayout and independent dashboard probes

Shared `FlowLayout` / `FlowHost` wrap toolbars and dashboard status tiles instead of clipping them. Dashboard client probes run asynchronously off the UI thread. Each configured client is checked independently, and a connection-settings change drops stale results. Usenet remains one search tier: SABnzbd is the schema 23 default; NZBGet is the optional Plugins selection.

## 2026-09-20 — NZBGet is a selectable Usenet client, not a new search source

SABnzbd remains the default downloader for the existing Prowlarr `usenet` tier.
Plugins can select NZBGet instead. New NZBs go to that client only. `sab:` and
`nzb:` handles stay on the client that accepted them when the preference changes.
Add-only NZBGet logins are not treated as connected. Schema version 23.

## 2026-09-20 — Review names, playback, artwork covers

- Review fills the table with sorting off, so Track / confidence / reason stay on the same row.
- A UUID or missing fingerprint title falls back to the embedded tag, then the filename.
- Rows with no local audio file (including exhausted wishlist searches) stay off Review. Play uses the selected file.
- Artwork shows those same cached cover files as thumbnails and a preview.

## 2026-09-20 — Album deletion and music-note icon

- Added confirmed album deletion through AlbumDeletionService and a locked repository transaction. Recycles registered files in configured zones, removes related records, preserves other libraries and unrelated files. Busy libraries and unfinished album acquisitions must be cleared first.
- Added multi-size music-note icon to Qt, executable, installer and package assets.
- Validation: 752 unit tests pass; ruff, strict mypy, import-linter and changed-file Black pass. Frozen, disposable installed, and real-profile startup checks pass. Updated the normal installation and verified the configuration hash was preserved; executable matches the build. Installer: packaging/output/VaultSeek-Setup-20260920.exe.
- Added disposable-file deletion tests covering failure/retry, root boundaries, archive tracks, shared albums, related records, real Recycle Bin and cancelled UI confirmation.

## 2026-09-20 — Upgrade startup repair and Archive selection review

- Inno upgrades now remove only the two obsolete bundled ICU DLLs; previous clean-install smoke tests did not cover leftover files in an existing installation.
- Archive selection in Library and Albums follows item IDs after sorting; missing metadata-only rows are excluded. Added Qt regression tests.
- Preserve user AppData and all acquisition/configuration contracts. Expanded Dashboard metadata/recommendation rows describe saved configuration, not independently verified connectivity.
- Final installer upgraded the real installation on 2026-09-20; executable hash matches dist, configuration hash is unchanged, and the real-profile main window responds. Existing Nicotine connection and qBittorrent login failures remain; Usenet connects. Git commit blocked by missing author identity.
- Validation: 742 unit tests pass; ruff, strict mypy, import-linter and changed-file Black pass. Upgrade test seeded with obsolete ICU files reaches a responding VaultSeek main window; existing installation also passes with isolated AppData.
- Whole-tree Black has four pre-existing failures (health_legend, setup_wizard, test_settings_cleanup, test_provider_manager); changed files are checked separately.

## 2026-09-14 — Connection status, faster local detect, pipeline workers

- Dashboard **Music tools** uses waterfall ids (`usenet` / `prowlarr_public` /
  `prowlarr_private`), not the legacy `prowlarr` id.
- Local detection probes ports in parallel; SAB `vaultseek` category and
  qBittorrent save path can be copied when present.
- Settings → Application exposes hash/metadata/scanner worker counts (restart).

## 2026-09-14 — GUI cleanup + help merged onto GitLab `main`

Summary

- Other AI on `gitlab/main`: acquisition search waterfall (schema v22, `a1ba7f2`)
  and `AGENTS.md` onboarding (`e409448`).
- This session: GUI ownership cleanup, fleshed-out F1 help, then merge onto
  `main` so both AIs share one branch.
- Settings vs Plugins one-writer contract (ADR-0018). Nicotine+ save uses
  `replace()` so username/password survive. Wizard updates the active library.
- Wishlist interval is Settings-only (Dashboard read-only). Wanted actions
  moved to Wishlist. Shared widgets: `quality_fields`, `page_header`,
  `health_legend`. Duplicate unused `services/dto/browse_dto.py` removed.
- Help: `docs/HELP.html` + `docs/USER_GUIDE.md` include waterfall, ownership
  table, and download-setup matrix.

Files modified

- `src/vaultseek/gui/views/*` (settings, plugins, dashboard, wizard, pages)
- `src/vaultseek/gui/widgets/{quality_fields,page_header,health_legend}.py`
- `docs/HELP.html`, `docs/USER_GUIDE.md`, `AGENTS.md`, `docs/DECISIONS.md`
- `tests/unit/gui/test_settings_cleanup.py`, `test_user_help.py`

Architectural decisions

- ADR-0018 Settings vs Plugins ownership.
- Waterfall UI lives under **Settings → Wishlist & downloads**, not a separate
  Acquisition settings group.

Remaining work

- User will add plugin credentials, then live Nicotine+ / Prowlarr tests.
- `master` still tracks older `gitlab/master`; do not assume it matches `main`.

Known issues

- Stash `gui-cleanup-and-help-2026-09-14` was used for the merge; drop after
  this commit is on `gitlab/main`.

Next session goal

Live acquisition tests once credentials are in place. Pull `gitlab/main` first.

---

## 2026-07-20 — Phase 1 + Acquisition foundation

Summary

- Forked MusicVault → VaultSeek at `C:\Users\user\Projects\VaultSeek`.
- Rebranded `musicvault` → `vaultseek`; data dir `%APPDATA%\VaultSeek`.
- Imported planning docs + ARCHITECTURAL_UPDATE_001; ADR-0016, ADR-0017.
- AcquisitionProvider Protocol, ProviderManager, stub provider.
- AcquisitionJob state machine + in-memory AcquisitionEngine.
- Local commit `926777a` pushed to https://github.com/oceanmasterza/VaultSeek (`origin/master` in sync).

Recommended refactors (no user-visible change, before new features)

- Rename pipeline `Job` references in UI to avoid confusion with `AcquisitionJob` (internal only).
- Add `acquisition_jobs` DB table before wiring Missing Media Analyzer.
- Route future search/download through AcquisitionEngine only (never UI → Provider).

Next session goal

Persist AcquisitionJob + Missing Media Analyzer.

---

## 2026-07-20 — Phase 2: Persist jobs + gap analyzer

Summary

- Added `acquisition_jobs` table (Alembic 0006) + `AcquisitionJobRepository`.
- Refactored `AcquisitionEngine` to persist via repository (same public API).
- `MissingMediaAnalyzer` compares library tracklists vs MusicBrainz; `create_jobs_for_library` creates MISSING_TRACK jobs.
- Wired repo + analyzer in `Container`.

Recommended refactors (non-user-visible)

- `SearchDispatcher` should advance job state and store raw results in `job.extra` (Phase 6).
- Connect acquisition providers from config on bootstrap (Phase 3).

Next session goal

Provider config hardening, Nicotine+ skeleton, search/scoring/download skeletons.

---

## 2026-07-20 — Phases 3–8 skeletons

Summary

- `AcquisitionConfig` / schema v8 + bootstrap `connect_acquisition_providers`.
- `NicotinePlusProvider` skeleton (TCP probe; graceful without client).
- `SearchDispatcher`, `ScoringEngine`, `DownloadManager` wired in `Container`.
- 574 tests passing.

Recommended refactors (non-user-visible)

- Persist search results on `AcquisitionJob.extra` during COLLECTING_RESULTS.
- Replace sync Nicotine+ probe with real RPC when API surface is chosen.
- Persist download handles (survive restart).

Next session goal

Verification + import pipeline integration; real Nicotine+ search/download.


---

## 2026-07-20 — Phases 9–10: Verification + Import skeletons

Summary

- `VerificationEngine` + `VerificationResult` (path checks, metadata hints, stubs).
- `ImportPipeline` + `ImportResult` with mandatory `run_after_verification` gate.
- Wired in `Container`; unit tests for pass/fail/complete paths.

Recommended refactors (non-user-visible)

- Persist `local_paths` on `AcquisitionJob.extra` when downloads complete.
- Replace fingerprint/duplicate stubs with FingerprintWorker + DuplicateMatcher.
- Hand off ImportPipeline to OrganizerWorker / ArtworkWorker / MediaServerWorker.

Also added

- `DownloadManager.complete` persists `local_paths` and advances to VERIFYING.
- `AcquisitionWorkflow.finish_download` chains verify→import.

Next session goal

Also added NicotinePlusRpcClient / FakeRpcClient injection point.

Next session goal

Implement real Nicotine+ RPC transport; harden verification with fingerprints.


---

## 2026-07-20 — Nicotine+ NDJSON transport + verify/import hand-off

Summary

- Researched Nicotine+: no official TCP/JSON RPC; community `api-nicotine-plus`
  is HTTP on 12339. VaultSeek defines a clear NDJSON socket protocol.
- `LocalSocketRpcClient` (graceful offline) + working `FakeRpcClient` path.
- `VerificationEngine`: SHA-256 duplicate checks via `DuplicateRepository`,
  embedded tags via `LocalTagsProvider`, optional Chromaprint fingerprint
  duplicate checks (soft-skip when fpcalc unavailable).
- `ImportPipeline`: stages verified files into library Incoming and enqueues
  `SCAN_DIRECTORY` (existing organize/artwork/media-server chain); optional
  `SYNC_MEDIA_SERVER`.
- Wired in `Container`.

Recommended refactors (non-user-visible)

- Ship or document a Nicotine+ companion plugin that speaks the NDJSON protocol
  (or adapt `HttpApiRpcClient` to palaueb/api-nicotine-plus).
- Persist verification digests on `AcquisitionJob.extra`.
- Defer media-server sync until organize completes (today optional early enqueue).

Next session goal

Scheduled automation; NDJSON companion plugin; richer result picker UI.


---

## 2026-07-21 — HTTP adapter, Acquisition UI, auto-acquire

Summary

- `HttpApiRpcClient` for community api-nicotine-plus (search/download/status).
- `AcquisitionRunner`: search → score → auto-acquire threshold → poll downloads.
- Acquisition page in GUI (wishlist, scan missing, auto-acquire, manual top pick, result picker).
- `AcquisitionAutomationService` background loop for auto-acquire + verify/import polling.
- Retry scheduling for download/verification/import failures (exponential backoff).
- Settings: auto-acquire threshold + Nicotine+ transport (socket/http).
- Config schema v9 (`auto_acquire_threshold`, `transport`, `api_port`, `api_token`).
- 601 tests passing.

Recommended refactors (non-user-visible)

- Dashboard acquisition job counts on the main status/dashboard pages.
- Dedicated acquisition reports view (beyond last-note column).

Next session goal

Acquisition reports and richer history UI.


---

Template

Date

Summary

Files modified

Architectural decisions

Remaining work

Known issues

Next session goal

---

# AI Session Checklist

Before writing code

Read:

PROJECT_PLAN.md

ARCHITECTURE.md

AI_RULES.md

DEVELOPMENT_ROADMAP.md

Before finishing

Update:

Progress

Completed tasks

Roadmap

Session Notes

Technical Debt

Known Issues

---

# Golden Rule

Never sacrifice architecture for speed.

Every feature should make VaultSeek easier to extend.

If an implementation makes future providers harder to add, redesign it before writing code.

Build foundations first.

Features come second.