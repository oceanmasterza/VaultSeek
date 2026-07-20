# ARCHITECTURAL_UPDATE_001

## Purpose

This document supersedes parts of the original specification following additional research into Soularr, Nicotine+, the Soulseek protocol, and long-term project planning.

These are architectural refinements, not a redesign.

---

# 1. Rename Search Engine to Acquisition Engine

The subsystem previously referred to as the Search Engine is now the **Acquisition Engine**.

Searching is only one step in the acquisition lifecycle.

The Acquisition Engine is responsible for the complete workflow from identifying missing music through to importing verified files.

The Acquisition Engine contains:

- Missing Media Analyzer
- Acquisition Job Scheduler
- Search Dispatcher
- Provider Manager
- Result Collector
- Scoring Engine
- Download Manager
- Verification Engine
- Import Pipeline

All future development should use the term **Acquisition Engine**.

---

# 2. Introduce Acquisition Jobs

The central object in VaultSeek is now an `AcquisitionJob`.

Everything revolves around jobs rather than searches.

An AcquisitionJob represents the complete lifecycle of acquiring an album, track or quality upgrade.

Typical properties include:

- Artist
- Album
- Release
- MusicBrainz Release ID
- Preferred Codec
- Preferred Bit Depth
- Preferred Country
- Preferred Providers
- Search Results
- Selected Result
- Download Status
- Verification Status
- Import Status
- Retry Count
- Priority
- Progress
- History

Every subsystem updates the AcquisitionJob rather than communicating directly with one another.

---

# 3. Acquisition Job State Machine

Every AcquisitionJob should follow a deterministic state machine.

Typical states:

Created

↓

Queued

↓

Searching

↓

CollectingResults

↓

Scoring

↓

WaitingForUser (optional)

↓

Downloading

↓

Verifying

↓

Importing

↓

Completed

Failure states include:

NoResults

RetryScheduled

DownloadFailed

VerificationFailed

ImportFailed

Cancelled

This state machine becomes the single source of truth for workflow status.

---

# 4. Provider Independence

VaultSeek must never become tightly coupled to Nicotine+.

Nicotine+ is simply the first Provider.

The Provider Framework remains the architectural boundary between VaultSeek and external systems.

Future providers should require no architectural changes.

Potential future providers include:

- Native Soulseek
- Local Archive
- SMB
- FTP
- WebDAV
- HTTP Indexes
- Lidarr
- qBittorrent
- Usenet
- Cloud Storage

---

# 5. Learnings from Soularr

Research into Soularr confirmed several architectural decisions.

Adopt:

✔ Separate searching from downloading.

✔ Treat downloads as asynchronous workflows.

✔ Allow providers to focus only on communication.

✔ Verify downloads before import.

Do NOT copy:

✘ Tight coupling to a single ecosystem.

✘ Provider-specific business logic.

✘ Search-driven architecture.

VaultSeek should remain acquisition-driven.

---

# 6. Verification Remains Mandatory

No downloaded file should ever be imported automatically.

Every completed download must pass:

- Metadata validation
- Fingerprint validation
- Duplicate detection
- Release verification

Only verified content enters the managed library.

---

# 7. Reuse MusicVault

Continue reusing existing MusicVault functionality wherever practical.

Do not duplicate existing implementations for:

- Fingerprinting
- Metadata
- Artwork
- Library organisation
- Duplicate detection
- Media server refresh

VaultSeek should extend MusicVault, not replace it.

---

# 8. Future Shared Core

Long-term direction remains unchanged.

MusicVault and VaultSeek should gradually evolve towards a shared reusable core library.

Example:

MusicVault.Core

containing:

- Library
- Metadata
- Fingerprinting
- Artwork
- Import
- Media Servers

Both applications will consume this shared library.

---

# 9. Quality Upgrade Jobs

Introduce a second AcquisitionJob type.

Instead of only downloading missing albums, VaultSeek should eventually support quality upgrades.

Example:

Current Library

Artist

Album

MP3

↓

Provider Search

↓

FLAC Found

↓

Acquire

↓

Verify

↓

Replace

↓

Refresh Library

Quality upgrades should become first-class citizens of the Acquisition Engine.

---

# 10. Architectural Principle

VaultSeek is not a Soulseek client.

VaultSeek is an intelligent music acquisition platform.

Searching is only one part of acquisition.

Every architectural decision should strengthen this separation of concerns.