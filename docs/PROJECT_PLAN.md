# PROJECT_PLAN.md

> **Terminology (2026-07):** The central subsystem is the **Acquisition Engine**, not “Search Engine”.
> Search dispatch is a step inside it. See [ARCHITECTURAL_UPDATE_001.md](ARCHITECTURAL_UPDATE_001.md).

# VaultSeek

## Project Overview

VaultSeek is an AI-developed Windows desktop application built from the MusicVault codebase.

Where MusicVault organises an existing music library, VaultSeek is responsible for discovering, acquiring and importing missing music.

VaultSeek analyses the existing library, determines which albums or tracks are missing, searches configured providers, intelligently selects the highest-quality match, downloads it, verifies the contents, imports it into the managed library and triggers media server rescans.

The application should feel like the natural companion to MusicVault.

**MusicVault**
> Organise what you have.

**VaultSeek**
> Find what you're missing.

---

# Primary Objectives

The project must:

- Remain fully compatible with MusicVault libraries.
- Reuse as much MusicVault functionality as possible.
- Keep the codebase modular.
- Be developed almost entirely using AI pair programming.
- Be easy for AI assistants to understand and extend.
- Allow new download providers without changing core logic.
- Require minimal user interaction for normal workflows.
- Prefer automation while keeping the user in control.

---

# Non Goals

VaultSeek is NOT intended to become a replacement for download clients.

Its responsibility is to:

- discover music
- evaluate search results
- coordinate downloads
- verify downloaded files
- import into the managed library

Actual downloading is delegated to Providers.

---

# Overall Workflow

```
Scan Library
        │
        ▼
Fingerprint Audio
        │
        ▼
Identify Releases
        │
        ▼
Detect Missing Albums / Tracks
        │
        ▼
Generate Search Jobs
        │
        ▼
Provider Search
        │
        ▼
Collect Results
        │
        ▼
Score Results
        │
        ▼
Select Best Match
        │
        ▼
Download
        │
        ▼
Verify
        │
        ▼
Import into Library
        │
        ▼
Trigger Media Server Refresh
```

---

# High Level Architecture

```
VaultSeek
│
├── UI
├── Library Manager
├── Metadata Engine
├── Missing Media Analyzer
├── Acquisition Engine
├── Provider Framework
├── Download Manager
├── Import Manager
├── Media Server Manager
└── Logging
```

Every component should have a single responsibility.

No component should know implementation details of another.

All communication should happen through interfaces.

---

# Architectural Philosophy

The application must follow SOLID principles.

Prefer:

- Dependency Injection
- Composition over inheritance
- MVVM
- Async programming
- Interfaces
- Small classes
- Small methods

Avoid:

- Static state
- Hidden dependencies
- Circular references
- Tight coupling
- Duplicate logic

---

# Provider Framework

VaultSeek must support multiple music acquisition providers.

The core application must know nothing about provider implementation.

Every provider implements a common interface.

Example:

```
IProvider

ConnectAsync()

DisconnectAsync()

SearchAsync()

BrowseAsync()

DownloadAsync()

CancelAsync()

GetStatusAsync()

Capabilities
```

Providers are responsible only for communicating with external systems.

Providers never modify the library directly.

---

# Provider Manager

Responsible for:

- loading providers
- configuration
- lifecycle
- connection state
- capability detection
- selecting active provider

The Provider Manager is the only component allowed to communicate with providers.

---

# First Provider

## Nicotine+ Provider

The first implementation will integrate with an installed Nicotine+ client.

The provider should communicate with Nicotine+ rather than implementing the Soulseek protocol directly.

Reasons:

- reuse mature networking implementation
- avoid maintaining protocol compatibility
- reduce development complexity
- leverage existing download management

Responsibilities:

- Detect Nicotine+
- Connect
- Verify availability
- Submit searches
- Receive asynchronous search results
- Parse responses
- Queue downloads
- Monitor progress
- Detect completion
- Return downloaded file locations

Provider-specific logic must never exist elsewhere.

---

# Future Providers

The Provider Framework must support future implementations such as:

- Native Soulseek Protocol
- Local Archive
- SMB Share
- FTP
- WebDAV
- HTTP Index
- Lidarr
- qBittorrent
- Usenet
- Custom Providers

Adding a new provider should require no modification of existing providers.

---

# Missing Media Analyzer

Responsible for determining what music is missing.

Inputs:

- MusicBrainz metadata
- existing library
- release information
- track information

Outputs:

Missing Albums

Missing Tracks

Better Quality Available

Incomplete Releases

Never performs searching.

---

# Search Dispatcher (Acquisition Engine)

The Search Dispatcher converts metadata into provider-independent `SearchRequest` objects.

Example Input:

Artist:
Pink Floyd

Album:
The Wall

Year:
1979

Preferred Format:
FLAC

Output:

SearchRequest

The Search Dispatcher never communicates directly with providers — only via Provider Manager.

---

# Search Result Collection

Providers return search results asynchronously.

The Result Collector gathers results until:

- timeout
- user cancellation
- maximum result count

Then passes the entire collection to the Scoring Engine.

---

# Scoring Engine

Every result receives a confidence score.

Scoring criteria include:

Artist Match

Album Match

Track Count

Codec

Bit Depth

Sample Rate

Folder Structure

Year

Complete Album

Release Match

Trusted Source

Preferred File Type

File Size

Missing Tracks Covered

Score weights should be configurable.

The highest scoring result becomes the recommended download.

---

# Download Manager

Responsible for:

- queue management
- progress reporting
- retries
- cancellation
- resume
- failures
- history

Providers perform transfers.

The Download Manager manages workflow.

---

# Verification Engine

Every completed download must be verified.

Checks include:

- readable files
- supported formats
- fingerprint validation
- metadata comparison
- release verification

Rejected downloads are never imported.

---

# Import Manager

Responsible for:

- fingerprinting
- metadata updates
- artwork
- organisation
- duplicate detection
- media server refresh

Reuse existing MusicVault logic wherever possible.

---

# Media Server Manager

Continue supporting:

- Navidrome
- Jellyfin
- Plex

Automatically trigger rescans after successful imports.

---

# Settings

Configuration should include:

Providers

Download Folder

Concurrent Downloads

Preferred Codec

Preferred Bit Depth

Maximum File Size

Search Timeout

Scoring Weights

Logging Level

Media Servers

Automation Rules

---

# Logging

Every subsystem must use structured logging.

Include:

Information

Warning

Error

Debug

Trace

Logs should make troubleshooting easy.

---

# Error Handling

Never silently ignore exceptions.

Recover whenever possible.

Provide meaningful user feedback.

Log enough information for debugging.

---

# AI Development Standards

This project is intentionally designed for AI-assisted development.

Every module should therefore be:

Highly documented

Self-contained

Small

Descriptive

Predictable

Strongly typed

Every public class should include XML documentation.

Every public method should include XML documentation.

Complex algorithms should include explanatory comments.

Avoid "clever" code.

Prefer readability over brevity.

---

# Coding Standards

Use:

SOLID

MVVM

Dependency Injection

Async/Await

CancellationToken

Nullable Reference Types

Structured Logging

Interfaces

Unit Testing

Avoid:

Magic strings

Large classes

Large methods

Duplicate code

Hidden dependencies

Global mutable state

---

# Development Roadmap

## Phase 1

Create VaultSeek repository.

Rename solution.

Ensure project builds.

No functional changes.

---

## Phase 2

Extract reusable components.

Separate:

Library

Metadata

Artwork

Import

Media Server

Prepare Provider Framework.

---

## Phase 3

Implement Provider Framework.

Provider discovery

Provider loading

Provider configuration

Dependency Injection

---

## Phase 4

Implement Nicotine+ Provider.

Connection

Authentication

Search

Result collection

Download queue

Progress

Completion

---

## Phase 5

Implement Search Dispatcher and result collection within the Acquisition Engine.

Metadata conversion

Search generation

Request scheduling

---

## Phase 6

Implement Scoring Engine.

Weighted scoring

Configurable priorities

Recommendation logic

---

## Phase 7

Implement Download Manager.

Queue

Retries

Resume

History

Progress

---

## Phase 8

Implement Verification Engine.

Fingerprint validation

Metadata comparison

Release verification

---

## Phase 9

Implement Import Pipeline.

Duplicate detection

Artwork

Library organisation

Media server refresh

---

## Phase 10

User Interface.

Search status

Progress

Recommendations

Download history

Settings

Provider management

---

# Success Criteria

A successful workflow should require only:

1. Scan library.

2. Detect missing album.

3. User clicks "Acquire".

4. VaultSeek searches configured providers.

5. Search results are automatically scored.

6. Best result is selected.

7. Download begins.

8. Download completes.

9. Files are verified.

10. Files are imported.

11. Media server refreshes.

12. Album appears in the user's library.

The entire process should require minimal user intervention.

---

# Long-Term Vision

VaultSeek should become a provider-agnostic music acquisition platform.

The core application should never care where music comes from.

Providers should be interchangeable.

Future providers should be installable without modifying the core application.

The architecture should make it possible to support entirely new acquisition methods years into the future without major refactoring.

---

# AI Instructions

When implementing features:

- Read this document before making architectural decisions.
- Follow the documented architecture.
- Do not bypass abstraction layers.
- Reuse existing MusicVault components wherever practical.
- Keep classes focused on a single responsibility.
- Write maintainable, readable code.
- Document all public APIs.
- Prefer incremental, testable implementations.
- If a requested feature conflicts with this document, propose an architectural update before implementing it.