# DEVELOPMENT_ROADMAP.md

# VaultSeek Development Roadmap

Version: 1.1

Status: Active development

Overall Progress: 15%

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

Phase 2 – Acquisition Engine foundation

Current Sprint

Sprint 2

Current Goal

AcquisitionJob state machine + ProviderManager stub wired; next: persist jobs,
Missing Media Analyzer, Nicotine+ provider.

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

🟡 In Progress

Tasks

AcquisitionJob entity + state machine ✅

AcquisitionEngine skeleton ✅

Provider Framework stub ✅

Import ARCHITECTURAL_UPDATE_001 ✅

Persist AcquisitionJob (DB)

Missing Media Analyzer

Deliverable

Stable AcquisitionJob API; ready for Nicotine+ provider.

---

## Phase 3

Provider Framework

Status

⬜ Not Started

Tasks

Create Provider interfaces

Create Provider Manager

Provider registration

Configuration

Plugin loading

Dependency Injection

Deliverable

Application supports multiple providers.

---

## Phase 4

Nicotine+ Provider

Status

⬜ Not Started

Tasks

Connection

Availability detection

Authentication (if required)

Search

Receive results

Queue downloads

Monitor progress

Completion detection

Deliverable

Searches and downloads through Nicotine+.

---

## Phase 5

Missing Media Detection

Status

⬜ Not Started

Tasks

Album analysis

Track analysis

Incomplete release detection

Quality comparison

Deliverable

Accurate missing-media identification.

---

## Phase 6

Search Engine

Status

⬜ Not Started

Tasks

Generate SearchRequests

Provider dispatch

Timeout handling

Cancellation

Deliverable

Provider-independent searching.

---

## Phase 7

Scoring Engine

Status

⬜ Not Started

Tasks

Normalize results

Weighted scoring

Recommendation engine

Configurable priorities

Deliverable

Automatic best-match selection.

---

## Phase 8

Download Manager

Status

⬜ Not Started

Tasks

Queue

Retries

Resume

Cancellation

History

Progress

Deliverable

Reliable download workflow.

---

## Phase 9

Verification Engine

Status

⬜ Not Started

Tasks

Fingerprint

Metadata validation

Duplicate detection

Release verification

Deliverable

Safe automatic importing.

---

## Phase 10

Import Pipeline

Status

⬜ Not Started

Tasks

Artwork

Organisation

Metadata

Library updates

Media server refresh

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