# ARCHITECTURE.md

# VaultSeek Architecture

## Overview

VaultSeek is designed as a modular, provider-driven Windows desktop application.

The application extends the ideas of MusicVault by adding intelligent music discovery and acquisition while preserving the existing library management pipeline.

The architecture intentionally separates concerns so that new providers, metadata sources and workflows can be added without modifying existing components.

---

# High-Level Architecture

```
                     +--------------------+
                     |        UI          |
                     +----------+---------+
                                |
                                v
                     +--------------------+
                     | Application Layer  |
                     +----------+---------+
                                |
      +-------------------------+-------------------------+
      |                         |                         |
      v                         v                         v
+-------------+        +----------------+        +----------------+
| Library     |        | Search Engine  |        | ProviderManager|
+------+------+        +-------+--------+        +--------+-------+
       |                       |                          |
       |                       |                          |
       |                       |                          |
       |              +--------+---------+                |
       |              | Scoring Engine   |                |
       |              +--------+---------+                |
       |                       |                          |
       |                       v                          |
       |              +------------------+                |
       |              | DownloadManager  |                |
       |              +--------+---------+                |
       |                       |                          |
       |                       v                          |
       |              +------------------+                |
       |              | Verification     |                |
       |              +--------+---------+                |
       |                       |                          |
       +-----------------------+--------------------------+
                               |
                               v
                    +------------------------+
                    | Import Manager         |
                    +-----------+------------+
                                |
                                v
                    +------------------------+
                    | Media Server Manager   |
                    +------------------------+
```

---

# Layer Responsibilities

## UI

Responsible only for presentation.

Never contains business logic.

Communicates with ViewModels only.

---

## ViewModels

Responsible for:

- commands
- data binding
- progress updates
- user interaction

Never performs searching.

Never downloads files.

Never communicates with providers directly.

---

## Services

Business logic belongs here.

Examples:

LibraryService

MetadataService

SearchService

DownloadService

ImportService

---

## Providers

Providers communicate with external systems.

Examples:

NicotineProvider

SoulseekProvider

FTPProvider

WebDAVProvider

Future providers

Providers never know about the library.

Providers simply return search results and downloaded files.

---

# Dependency Rules

Allowed:

```
UI
↓

ViewModel
↓

Service
↓

ProviderManager
↓

Provider
```

Not Allowed:

```
UI → Provider

Provider → UI

Provider → Database

ViewModel → Provider

Provider → Import Manager
```

Dependencies must always point downward.

---

# Plugin Architecture

```
Providers/

    Nicotine/

        NicotineProvider.cs

        NicotineSearch.cs

        NicotineDownload.cs

        NicotineConfiguration.cs

    Soulseek/

    FTP/

    Local/
```

Every provider exposes:

```
Name

Version

Capabilities

Configuration

Connect()

Disconnect()

Search()

Download()

Cancel()

Dispose()
```

---

# Search Pipeline

```
Missing Album

↓

Metadata Lookup

↓

Search Request

↓

Provider Search

↓

Collect Results

↓

Score Results

↓

Choose Best

↓

Download

↓

Verify

↓

Import
```

Every step should be independently testable.

---

# Result Scoring Pipeline

```
Search Results

↓

Normalize

↓

Artist Match

↓

Album Match

↓

Track Count

↓

Codec

↓

Bit Depth

↓

Year

↓

Folder Structure

↓

Trusted Source

↓

Final Score
```

No provider-specific scoring.

All providers produce normalized results.

---

# Import Pipeline

```
Downloaded Files

↓

Read Metadata

↓

Fingerprint

↓

MusicBrainz Validation

↓

Duplicate Detection

↓

Artwork

↓

Organise

↓

Library

↓

Media Server Refresh
```

Reuse MusicVault code wherever possible.

---

# Configuration

All configuration belongs in strongly typed objects.

Example:

```
ProviderSettings

DownloadSettings

SearchSettings

MediaServerSettings

LoggingSettings
```

Never use dictionaries for application configuration.

---

# Logging

Every subsystem receives an ILogger.

Never use Console.WriteLine().

Logging should include:

Information

Warning

Error

Debug

Trace

---

# Threading

Everything should be asynchronous.

Long-running work must never block the UI.

Use:

async

await

CancellationToken

IProgress<T>

Never use Thread.Sleep().

---

# Error Handling

Failures should never crash the application.

Recover whenever practical.

Retry where appropriate.

Log everything.

Provide meaningful feedback.

---

# Testing Strategy

Each service should be independently testable.

Providers should be mockable.

Every interface should have unit tests.

Integration tests should validate provider communication.

---

# Shared Code Strategy

MusicVault and VaultSeek should gradually evolve toward a shared reusable core.

Proposed future structure:

```
MusicVault.Core

    Fingerprinting

    Metadata

    Artwork

    Library

    Import

    Media Servers

MusicVault

VaultSeek
```

Avoid duplicating business logic whenever possible.

---

# Design Principles

Single Responsibility

Open/Closed

Dependency Inversion

Composition over Inheritance

Interfaces over Concrete Types

Small Classes

Small Methods

Readable Code

Predictable Behaviour
