# DECISIONS.md

# VaultSeek Architecture Decision Records (ADR)

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

The Search Engine produces SearchRequest objects.

Providers translate SearchRequest into provider-specific implementations.

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