# VaultSeek Project Context

## Product and runtime

- **Purpose:** Windows music-library companion that finds missing or upgradeable music, acquires it through configured sources, verifies it, imports it, organizes it, and refreshes media servers.
- **Runtime:** Python 3.12+, PySide6, SQLite/SQLAlchemy Core/Alembic, Container DI, `typing.Protocol`; package root `src/vaultseek/`; user data `%APPDATA%\\VaultSeek`.
- **Key dependencies:** PySide6, SQLAlchemy, Alembic, mutagen, pyacoustid/Chromaprint, rapidfuzz, Pillow, requests, Send2Trash, psutil, loguru, shazamio. Build uses PyInstaller.

## Architecture map

- `core/`: typed configuration, migrations, Container wiring.
- `models/`: domain entities and Protocols, isolated from UI/DB/services/workers/plugins.
- `services/`: Acquisition Engine orchestration, ProviderManager, local setup, connection checks, import and verification coordination.
- `plugins/builtin/`: external integrations only: Nicotine+, Prowlarr/qBittorrent, SABnzbd, NZBGet, metadata and media servers.
- `workers/`: library scan, identify, organize, artwork, media-server and pipeline jobs.
- `gui/`: PySide6 presentation pages and reusable widgets; accesses work through Container services. Shared `FlowLayout` wraps toolbars and status tiles instead of clipping them.
- `db/`: SQLAlchemy Core tables, repositories, Alembic migrations.

## Acquisition behavior

- Default waterfall (schema 23): Nicotine+ → Prowlarr Usenet (SABnzbd by default, or selectable NZBGet; one search tier) → Prowlarr public torrents/qBittorrent → private torrents/qBittorrent.
- With `search_waterfall=True`, stop at the first connected source returning hits; wait 15 seconds after an empty tier by default. A Nicotine throttle failure must continue to later tiers.
- The Verification Pipeline is mandatory before the Import Pipeline. Providers return normalized results and never alter library state.
- A download start that gets no handle moves through `downloading` before `download_failed`. `scoring -> download_failed` stays illegal, so one disconnected peer cannot abort the rest of the acquisition tick.

## Persisted data

- Core library: `libraries`, `artists`, `albums`, `tracks`, `file_identity`, `metadata_confidence`.
- Library operations: `artwork`, mappings, `jobs`, `review_items`, `rules`, duplicate tables, `operations`, `change_history`, `rollback_snapshots`, `trusted_folders`.
- Integration/acquisition: `media_server_state`, `acquisition_jobs`; IDs are UUIDv7 BLOBs and timestamps ISO-8601 text.

## Current milestone

- Version 1.1.0; active Phase 6 automation and polish.
- Recent work: schema 23 selectable Usenet client (SABnzbd default, optional NZBGet), shared responsive FlowLayout, and independent asynchronous dashboard client probes (one failure does not cancel the others; stale results drop when settings change).
- Current priorities: safely archive/remove selected tracks or albums, replace dashboard status prose with compact tested-readiness indicators, live provider validation, and a measured packaging-size audit.
- Identify/Review: Incoming songs can auto-match library tracklists (provenance-aware); Prefer lossless still enqueues FLAC QUALITY_UPGRADE after LIBRARY land even when MP3 meets min bitrate. Review Assign album + Play are first-class UI.
- Settings and Plugins reconnect acquisition providers off the UI thread; `ProviderManager` serializes connect/disconnect/search so those reconnects cannot race an in-flight search. GUI status uses immutable connected/order snapshots and never waits on that lifecycle lock. Library/media dirty edits confirm before discard on library or media-plugin switch. Artwork is folded into Albums (Problems only).

## Collaboration

- Shared branch: `gitlab/main`; pull it before work. Cursor implements and pushes reviewed changes.
- Read `AGENTS.md`, `STANDING_RULES.md`, `PROJECT_CONTEXT.md`, `CHANGELOG_DECISIONS.md`, `docs/DECISIONS.md`, and the latest roadmap session note before architectural work.
- Packaging: the PyInstaller spec filters ambient ICU binaries that conflict with Qt 6.11. Onedir and a clean Inno-installed copy both reached the VaultSeek main window with temporary AppData.

- Upgrade regression: older installed ICU DLLs survive file overlay; installer cleanup targets these two files only. Archive selections now retain identity after sorting.

- Albums offers separate Archive and Delete actions. Delete recycles tracked files and removes library records after confirmation; the album remains in other libraries when shared. Music-note icon is packaged under gui/assets.

- Review identify: filename parser skips Nicotine UUID parents and parses `NN - Title`. Library tracklist matching uses provenance MBID + per-song duration/track evidence; identity auto-approves independently of quality (better LIBRARY copies archive via duplicate/organize after tagging). Assign album / `assignment_albums` / `assignment_slots` GUI contract on ReviewQueueService. Tag writes fail-closed via injected writer; missing files never approve as tagged. Acquisition provenance seeds absent artist/album before provider tag search (never job title). Quality-upgrade after LIBRARY organize with `source_track_id` dedupe; scoped upgrades honor Prefer lossless even when min bitrate is already met (library-health traffic lights keep minimum-acceptable semantics). Manual Assign on LIBRARY tracks enqueues same-zone reorganize.
