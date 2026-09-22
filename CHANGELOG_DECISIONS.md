# Change Log Decisions

- 2026-09-19: Project memory is kept in `PROJECT_CONTEXT.md`, standing implementation constraints in `STANDING_RULES.md`, and short dated decisions here. Detailed ADRs remain in `docs/DECISIONS.md`.
- 2026-09-19: Dashboard integration states use **Connected** only for active provider links and **Configured** for saved credentials or routes that have not had a compatible live check.
- 2026-09-14: Settings and Plugins own disjoint configuration fields and persist nested acquisition settings with `dataclasses.replace` (ADR-0018).
- 2026-09-14: Acquisition sources use a configurable waterfall: Nicotine+, Usenet/SABnzbd, public torrents/qBittorrent, then private torrents/qBittorrent.
- 2026-07-20: VaultSeek remains Python/PySide6 with Container DI and `typing.Protocol` plugin boundaries (ADR-0016).
- 2026-07-20: Acquisition Engine and AcquisitionJob are the workflow model; verification precedes import and Providers do not mutate the library (ADR-0017).
- 2026-09-19: Exclude ambient versioned ICU DLLs from frozen builds. Qt 6.11 requires Windows' unversioned ICU ABI; collecting Codex runtime Poppler ICU files caused QtWidgets to fail at load time.

- 2026-09-20: Inno removes obsolete `_internal/icuuc.dll` and `_internal/icudt78.dll` during upgrades; excluding them from a new payload alone does not repair existing installations. Archive actions resolve selection from sortable item data.
- 2026-09-20: Schema 23 adds optional NZBGet for the existing Usenet tier. SABnzbd stays the default. Plugins owns NZBGet and `usenet_download_client`. NZBGet is not a second search source.
- 2026-09-20: Shared `FlowLayout` wraps toolbars and dashboard tiles so controls stay fully visible when the window is narrow.
- 2026-09-20: Dashboard client probes run off the UI thread and independently. One client failure does not cancel the others. A settings change drops stale probe results.

- 2026-09-20: Review lists only songs with a local audio file and names them from an embedded tag or the filename when fingerprinting stored an id. Artwork shows the same album cover files as Albums.

- 2026-09-21: Settings/Plugins provider reconnect runs in the background and shares `ProviderManager.lifecycle` with search so concurrent reconnects cannot mutate providers mid-search. Library combo and media-plugin switches confirm before discarding dirty Settings edits. HELP documents Albums as the combined covers/Problems surface.
- 2026-09-21: ProviderManager GUI status reads immutable connected/order snapshots and never waits on the lifecycle lock held during search sleeps or reconnect network I/O.
- 2026-09-21: A refused download start from scoring or waiting-for-user enters downloading, then download_failed. scoring -> download_failed stays illegal so a disconnected Nicotine+ peer cannot abort the acquisition tick.

- 2026-09-22: Identify/Review album allocation: skip UUID download folders in filename parsing; match Incoming songs to existing library tracklists with hard gates (no title-only unique, provenance counts as one source, duration/version/MBID conflict blocks auto, better existing file blocks unique/assign). Review UI Assign album writes tags via backup+atomic replace, clears artwork_missing blockers, enqueues FETCH_ARTWORK. Quality-upgrade open-job dedupe. No config/waterfall changes.

- 2026-09-22: Identify workflow final: identity is independent of quality — better LIBRARY copies do not block unique match; after tagging, worse Incoming archives via organize/duplicate. Exact provenance MBID outranks other editions; slot keys retain full version text (no Frankenstein studio/demo merge). GUI contract `AlbumChoice` / `AlbumSlotChoice` + `assignment_albums` / `assignment_slots`. Scoped `QUALITY_UPGRADE` with `source_track_id` runs after OrganizerWorker LIBRARY placement. Provenance uses completed same-library download paths only.

- 2026-09-22: Workflow gates final — physical better-slot evidence; live Container config for scoped QUALITY_UPGRADE; retryable upgrade jobs dedupe; public `recording_identity` blocks contradictory upgrade hits (not track_count bypass); fail-closed tag writer injection; LIBRARY same-zone reorganize on Assign; organize reports quality_upgrade_error.

- 2026-09-22: Provenance-final — acquisition folder artist/album seeds the identify query after embedded tags and before MusicBrainz/Discogs (never job title; never overrides embedded artist). Named radio/single-edit variants stay distinct from bare studio.

- 2026-09-22: Quality-preference-final — scoped `create_job_for_track` treats Prefer lossless + lossy as an upgrade opportunity even when min bitrate is already met; library-health `track_meets_quality_prefs` unchanged.
- 2026-09-22: Delivery resume applied seven Incoming Salvation tracks to canonical album with collision-safe library names; QUALITY_UPGRADE jobs queued under Prefer lossless without claiming downloads; config unchanged.
