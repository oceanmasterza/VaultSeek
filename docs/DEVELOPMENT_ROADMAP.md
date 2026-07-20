# DEVELOPMENT_ROADMAP.md

# VaultSeek Development Roadmap

Version: 1.1

Status: Active development

Overall Progress: 34%

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

Phase 9–10 skeletons complete — next: live Nicotine+ I/O

Current Sprint

Sprint 3

Current Goal

Phases 9–10 skeletons wired. Next: live Nicotine+ search/download RPC;
fingerprint/duplicate verification; real ImportPipeline organize hand-off.
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

Live Nicotine+ search/download; harden verification with real fingerprints.


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