# DECISIONS.md

# VaultSeek Architecture Decision Records (ADR)

## 2026-09-14 — Settings vs Plugins: one writer per config key

Settings owns folders, quality, wishlist interval, Nicotine+, search waterfall.
Plugins owns Last.fm, Spotify, Prowlarr, qBittorrent, SABnzbd. Each page must
`dataclasses.replace` the existing `AcquisitionConfig` / nested client configs
so the other page’s credentials survive. Dashboard must not write wishlist
hours. Nicotine+ Settings save must `replace(existing.nicotine_plus, …)` —
rebuilding `NicotinePlusConfig(...)` wiped username/password. See ADR-0018.

---

## 2026-09-14 — Acquisition search waterfall (Nicotine → Usenet → Prowlarr public/private)

Split the former single `prowlarr` acquisition provider into three searchable
tiers (`usenet`, `prowlarr_public`, `prowlarr_private`) sharing one Prowlarr API
and routing NZBs to SABnzbd / torrents to qBittorrent. `ProviderManager` supports
`search_waterfall` (stop after first hits) and `provider_search_delay_seconds`
between empty tiers. Default order puts Nicotine+ first. Settings exposes a
reorderable source list. Schema version **22**. See `AGENTS.md` and `PROWLARR.md`.

---

## 2026-09-14 — Local connection setup and responsive diagnostics

Keep the Acquisition Engine and provider boundary unchanged. Add a read-only,
injectable local configuration discovery service with explicit supported paths.
Discovery produces suggestions, never edits third-party files, enables providers,
or overwrites saved remote connections automatically. UI imports are reviewed in
the existing forms before saving. Reuse background tasks for connection tests;
keep network calls off the GUI thread. Preserve all configured fingerprint slots.
Setup instructions remain in bundled HELP.html, accessible offline and by topic.

---

## Purpose

This document records important architectural decisions made during the lifetime of the VaultSeek project.

Unlike PROJECT_PLAN.md, which defines the project's goals, this file explains **why** specific architectural decisions were made.

Future AI sessions should consult this document before proposing significant architectural changes.

If a proposed implementation conflicts with an existing decision, either:

- follow the documented decision, or
- create a new ADR explaining why it should be replaced.

Never silently reverse an existing architectural decision.

---

# ADR-0001

## Title

VaultSeek will remain a separate application from MusicVault.

### Status

Approved

### Date

2026-07-20

### Context

MusicVault already performs library organisation extremely well.

Adding acquisition directly into MusicVault would eventually create a very large application with multiple unrelated responsibilities.

### Decision

Create VaultSeek as a separate Windows application.

The two applications may eventually share common libraries but remain independent products.

### Consequences

Advantages

- Clear separation of responsibility
- Easier maintenance
- Independent release schedules
- Cleaner user experience

Disadvantages

- Shared functionality must eventually be extracted into reusable libraries.

---

# ADR-0002

## Title

Provider-Based Architecture

### Status

Approved

### Context

Different music sources will require different communication methods.

Examples:

Nicotine+

Soulseek

FTP

WebDAV

SMB

HTTP

Future providers

### Decision

Create a Provider Framework.

Every acquisition source becomes a Provider implementing a common interface.

### Consequences

New providers can be added without modifying existing code.

---

# ADR-0003

## Title

Nicotine+ is the first provider.

### Status

Approved

### Context

Implementing the Soulseek protocol from scratch is significantly more complex than communicating with an existing client.

Nicotine+ already provides:

Connection management

Downloads

Transfer queues

Networking

Protocol compatibility

### Decision

Implement Nicotine+ support first.

Native Soulseek support may be added later.

### Consequences

Faster development.

Less protocol maintenance.

---

# ADR-0004

## Title

Searches must be Provider Independent.

### Status

Approved

### Context

Business logic should not depend on individual providers.

### Decision

The Acquisition Engine's **Search Dispatcher** produces `SearchRequest` objects.

Providers translate SearchRequest into provider-specific implementations.

> **Note:** Earlier docs used “Search Engine” for this responsibility. ADR-0017 renames the overall subsystem to **Acquisition Engine**.

### Consequences

Search logic remains reusable.

---

# ADR-0005

## Title

Verification is Mandatory.

### Status

Approved

### Context

Downloaded files cannot be trusted.

### Decision

Every completed download must pass:

Metadata validation

Fingerprint validation

Duplicate detection

Release verification

before import.

### Consequences

Prevents incorrect albums entering the library.

---

# ADR-0006

## Title

Reuse MusicVault Components

### Status

Approved

### Context

MusicVault already contains reliable implementations for:

Fingerprinting

Artwork

Metadata

Organisation

Media server refresh

### Decision

Reuse existing functionality whenever practical.

Avoid rewriting stable code.

### Consequences

Less maintenance.

Greater consistency.

---

# ADR-0007

## Title

Everything Asynchronous

### Status

Approved

### Context

Searching and downloading are long-running operations.

### Decision

Use async/await throughout the application.

Long-running work must never block the UI.

### Consequences

Responsive user interface.

---

# ADR-0008

## Title

Dependency Injection Required

### Status

Approved

### Decision

All services are resolved through Dependency Injection.

Avoid direct instantiation.

### Consequences

Improved testing.

Improved modularity.

---

# ADR-0009

## Title

SOLID Principles are Mandatory

### Status

Approved

### Decision

The application follows SOLID design principles.

### Consequences

Greater maintainability.

---

# ADR-0010

## Title

AI Readability is a First-Class Requirement

### Status

Approved

### Context

This project is intentionally developed using AI pair programming.

### Decision

Code should be written primarily for readability.

Readable code is preferred over clever code.

### Consequences

Future AI sessions require less context.

Maintenance becomes easier.

---

# ADR-0011

## Title

Business Logic Lives in Services

### Status

Approved

### Context

UI should remain presentation-only.

### Decision

ViewModels coordinate.

Services perform work.

Providers communicate externally.

### Consequences

Cleaner separation of concerns.

---

# ADR-0012

## Title

Provider Framework Owns External Communication

### Status

Approved

### Decision

Only Providers communicate with external systems.

No other component should know communication details.

### Consequences

External systems remain isolated.

---

# ADR-0013

## Title

Downloaded Files are Imported through the Existing Pipeline

### Status

Approved

### Context

MusicVault already has a mature import process.

### Decision

VaultSeek downloads files only.

Import Manager performs organisation.

### Consequences

One consistent import workflow.

---

# ADR-0014

## Title

Scoring Engine is Provider Neutral

### Status

Approved

### Decision

Providers return normalized search results.

The Scoring Engine decides which result is best.

### Consequences

Consistent recommendations across providers.

---

# ADR-0015

## Title

Future Shared Core Library

### Status

Planned

### Context

MusicVault and VaultSeek share increasing amounts of logic.

### Decision

Extract reusable code into:

MusicVault.Core

Future applications reference this shared library.

### Consequences

Reduced duplication.

Shared bug fixes.

Cleaner architecture.

---

# ADR-0016

## Title

VaultSeek inherits MusicVault's Python / PySide6 runtime

### Status

Approved

### Date

2026-07-20

### Context

Planning documents use C# / MVVM vocabulary for clarity. MusicVault — the
codebase VaultSeek is forked from — is Python 3.14 + PySide6 with Container DI
and `typing.Protocol` for plugins.

### Decision

VaultSeek remains Python / PySide6. C# examples in planning docs are
conceptual. Map Interface → Protocol, DI → Container, ViewModel → thin Qt pages.

### Consequences

Phase 1 is a rename/rebrand fork, not a language port.

---

# ADR-0017

## Title

Acquisition Engine and AcquisitionJob are the core workflow model

### Status

Approved

### Date

2026-07-20

### Context

See ARCHITECTURAL_UPDATE_001.md. Searching is one step in acquisition; the
central object is AcquisitionJob with a deterministic state machine.

### Decision

1. Use **Acquisition Engine** (not Search Engine).
2. **AcquisitionJob** is the central domain object.
3. Subsystems update the job; they do not call each other directly.
4. Nicotine+ is the first Provider only.
5. Verification before import remains mandatory.

### Consequences

Code and docs use Acquisition Engine / AcquisitionJob terminology.

---

# ADR-0018

## Title

Settings and Plugins each own a disjoint set of config keys

### Status

Approved

### Date

2026-09-14

### Context

`AcquisitionConfig` holds Nicotine+, Prowlarr, qBittorrent, SABnzbd, quality,
wishlist interval, and search waterfall on one dataclass. Rebuilding that
object on Settings save wiped plugin credentials. The Dashboard also wrote
wishlist hours, so two screens raced. The setup wizard sometimes updated the
wrong library and reset onboarding tips.

### Decision

1. **One writer per key.** Settings writes folders, quality, wishlist interval,
   Nicotine+, `provider_order`, `search_waterfall`, `provider_search_delay_seconds`,
   theme, log level, Discogs, AcoustID, fingerprinting, media servers.
2. **Plugins** writes Last.fm, Spotify, Prowlarr, qBittorrent, SABnzbd and the
   matching `usenet` / `prowlarr_public` / `prowlarr_private` enable flags.
3. Both pages persist with `dataclasses.replace` on the existing nested objects.
   Never construct a fresh `AcquisitionConfig(...)` or `NicotinePlusConfig(...)`
   when saving.
4. Dashboard wishlist interval is read-only; Wanted actions live on Wishlist.
5. Wizard updates the **active** library, preserves Nicotine+ transport/port,
   writes `acoustid_endpoints`, and does not reset onboarding tips on re-run.

### Consequences

UI fields must not be duplicated across pages. Help / USER_GUIDE / AGENTS.md
must list the same ownership table. Tests in `tests/unit/gui/test_settings_cleanup.py`
guard the merge contract.

---

# Decision Template

When adding new decisions, use the following format.

---

# ADR-XXXX

## Title

### Status

Proposed

Approved

Deprecated

Superseded

### Date

YYYY-MM-DD

### Context

Why is this decision needed?

### Decision

What has been decided?

### Alternatives Considered

Option A

Option B

Option C

### Consequences

Advantages

Disadvantages

Future considerations

---

# Decision Rules

Every architectural change should either:

Reference an existing ADR

or

Create a new ADR.

Avoid undocumented architectural changes.

---

# Deprecated Decisions

Move obsolete decisions here rather than deleting them.

Understanding why a decision changed is valuable historical context.

---

# Future Candidate Decisions

Potential future ADRs include:

Native Soulseek implementation

Automatic quality upgrades

Multiple provider searching

Distributed searching

Plugin marketplace

Cloud provider support

Machine-learning scoring

Shared MusicVault.Core library

Offline metadata cache

Plugin security model

---

# Final Principle

Good architecture is a series of deliberate decisions.

This document preserves those decisions so neither humans nor AI need to rediscover them.

## 2026-09-20 — Explicit album deletion

AlbumDeletionService owns filesystem removal; AlbumRepository holds a SQLite write
transaction around preflight, related-record cleanup and recycling. No schema change.
Deletion is scoped to the active library, with configured-zone validation and no
recursive directory removal. Windows may permanently delete files when recycling is unavailable; the confirmation explicitly warns about this. Metadata changes commit
only after file recycling succeeds. Filesystem and SQLite cannot commit atomically:
on partial failure, database records roll back and files already recycled remain
recoverable in Windows. Pending/running/retry library jobs and unfinished acquisitions
for the album block deletion. Archive keeps its existing semantics.
