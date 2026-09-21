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
