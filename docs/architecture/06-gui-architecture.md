# 06 — GUI Architecture (v2)

> **Revision**: v2 — Review Queue, Job Monitor, Duplicate Viewer, Rules Editor added.
> See [10-revision-v2.md](10-revision-v2.md).

## Pattern: MVVM (unchanged)

Views → ViewModels → Application Services. ViewModels poll job queue and review queue status. Long operations never block the main thread.

## Main Window Layout

```
┌──────────────────────────────────────────────────────────────────┐
│  MusicVault                                         [─] [□] [×]  │
├──────────┬───────────────────────────────────────────────────────┤
│          │                                                       │
│ Dashboard│                  Content Area                         │
│ Library  │                                                       │
│ Review ● │   (swappable views — ● = badge count)                │
│ Artists  │                                                       │
│ Albums   │                                                       │
│ Duplicat.│                                                       │
│ Jobs     │                                                       │
│ Artwork  │                                                       │
│ Reports  │                                                       │
│ Rules    │                                                       │
│ Logs     │                                                       │
│ Settings │                                                       │
│ Plugins  │                                                       │
│          │                                                       │
├──────────┴───────────────────────────────────────────────────────┤
│ Jobs: 3 running │ 12 pending │ Review: 7 │ Last sync: 2m ago     │
└──────────────────────────────────────────────────────────────────┘
```

Sidebar badge on **Review** shows pending review item count.

## Pages

| Page | ViewModel | Primary Purpose |
|------|-----------|----------------|
| Dashboard | `DashboardViewModel` | Stats, job summary, recent activity |
| Library | `LibraryViewModel` | Browse tracks by zone (library/staging/archive) |
| **Review** | `ReviewViewModel` | Approve/reject/edit uncertain items |
| Artists | `ArtistsViewModel` | Artist list + albums |
| Albums | `AlbumsViewModel` | Album grid with artwork |
| **Duplicates** | `DuplicatesViewModel` | Visual duplicate comparison |
| **Jobs** | `JobMonitorViewModel` | Job queue monitor (render farm view) |
| Artwork | `ArtworkViewModel` | Missing/low-res artwork |
| Reports | `ReportsViewModel` | Generate and preview reports |
| **Rules** | `RulesViewModel` | Create/edit/test automation rules |
| Logs | `LogsViewModel` | Log viewer with filters |
| Settings | `SettingsViewModel` | All configuration |
| Plugins | `PluginsViewModel` | Enable/configure/prioritize plugins |

Bold = new in v2.

## Review Queue Page

The most important new page. Users spend significant time here.

### Layout

```
┌─────────────────────────────────────────────────────────────┐
│  Review Queue (7 pending)          [Filter ▼] [Sort ▼]      │
├─────────────────────────────────────────────────────────────┤
│  ┌─ Unknown Artist ──────────────────────────────────────┐  │
│  │  Track: "Indicator" (Incoming/staging/)               │  │
│  │  Best guess: Allen Watts (confidence: 72%)            │  │
│  │  Sources: MB 72% | Discogs 68% | Filename 45%       │  │
│  │  [Approve] [Edit] [Reject] [Defer]                    │  │
│  └───────────────────────────────────────────────────────┘  │
│  ┌─ Possible Duplicate ──────────────────────────────────┐  │
│  │  "Dark Side of the Moon" matches 2 existing copies    │  │
│  │  [View Comparison →]                                 │  │
│  └───────────────────────────────────────────────────────┘  │
│  ┌─ Metadata Conflict ───────────────────────────────────┐  │
│  │  Year: MB says 1973 (95%) | Discogs says 1974 (88%) │  │
│  │  [Accept MB] [Accept Discogs] [Edit] [Defer]          │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

Filter by type: Unknown Artist, Duplicate, Artwork Missing, Metadata Conflict, Low Quality, Rule Action.

### Review Actions

| Action | Effect |
|--------|--------|
| Approve | Apply metadata, move staging → library if ready |
| Edit | Open metadata editor, then approve |
| Reject | Mark rejected; file stays in staging |
| Defer | Hide until next session |

## Visual Duplicate Viewer

Full-page view opened from Duplicates page or Review Queue.

### Comparison Cards

```
┌─ Dark Side of the Moon ──────────────────────────────────────────┐
│  3 copies found · Best: FLAC 24-bit (score 100)                 │
├──────────────────┬──────────────────┬──────────────────────────┤
│  [Cover Art]     │  [Cover Art]     │  [Cover Art]             │
│                  │                  │                          │
│  ★ BEST          │                  │                          │
│  FLAC 24-bit     │  FLAC 16-bit     │  MP3 320                │
│  Score: 100      │  Score: 95       │  Score: 70              │
│  10 tracks       │  10 tracks       │  10 tracks              │
│  1.2 GB          │  423 MB          │  112 MB                 │
│  2024 Remaster   │  1973 Original   │  2024 Remaster          │
│  library/        │  library/        │  staging/               │
│                  │                  │                          │
│  [Keep]          │  [Archive]       │  [Archive]              │
│                  │  [Delete]        │  [Delete]               │
└──────────────────┴──────────────────┴──────────────────────────┘
```

### Metadata Diff Panel

Below cards: table showing fields that differ across copies, highlighted in yellow.

| Field | Copy 1 (24-bit) | Copy 2 (16-bit) | Copy 3 (MP3) |
|-------|-----------------|-----------------|--------------|
| Year | 2024 | 1973 | 2024 |
| Label | Pink Floyd Records | Harvest | Pink Floyd Records |
| Catalog | PFRLP24 | SHVL 804 | — |

### Actions

- **Keep** — mark as canonical; others become archive/delete candidates
- **Archive** — move to Archive zone (Send2Trash never used for Keep)
- **Delete** — Send2Trash with confirmation dialog

## Job Monitor Page

Render-farm style view of all background processing:

```
┌─ Job Monitor ────────────────────────────────────────────────────┐
│  [Pause All] [Retry Failed] [Clear Completed]                    │
├──────────────┬────────┬─────────────────────────┬────────┬──────┤
│  Type         │ Status │ Detail                  │ Time   │ Act  │
├──────────────┼────────┼─────────────────────────┼────────┼──────┤
│  fingerprint  │ ● RUN  │ Dark Side.flac          │ 12s    │ [×]  │
│  fingerprint  │ ● RUN  │ Wish You Were Here.flac │ 8s     │ [×]  │
│  metadata     │ ○ PEND │ (queued, 847 pending)   │ —      │      │
│  hash         │ ✓ DONE │ 14,231 completed today  │ —      │      │
│  artwork      │ ✗ FAIL │ Timeout (retry 2/3)      │ 45s    │ [↻]  │
└──────────────┴────────┴─────────────────────────┴────────┴──────┘
```

Summary bar: `847 pending · 3 running · 1 failed · 14,231 completed today`

## Rules Editor Page

Visual rule builder:

```
┌─ Rules ──────────────────────────────────────────────────────────┐
│  [+ New Rule]                                                    │
├──────────────────────────────────────────────────────────────────┤
│  ✓ Archive MP3 when FLAC exists                    Priority: 10  │
│    IF codec = mp3 AND has_lossless_duplicate = true              │
│    THEN move_to_zone(archive)                                    │
│    [Edit] [Disable] [Delete]                                     │
├──────────────────────────────────────────────────────────────────┤
│  ✓ Detect Various Artists                        Priority: 20  │
│    IF artist = "" AND filename contains "VA"                     │
│    THEN set_artist("Various Artists") + flag_review              │
│    [Edit] [Disable] [Delete]                                     │
└──────────────────────────────────────────────────────────────────┘
```

Rule editor dialog: condition builder (field/operator/value), action picker, "requires approval" checkbox, test against sample track.

## Library View — Zone Tabs

Library page has zone tabs:

```
[Library (48,231)] [Staging (14)] [Archive (892)] [Incoming (3)]
```

Staging tab shows items awaiting review with confidence badges. Incoming shows files detected by watch folder not yet processed.

## Threading (unchanged principles)

- All DB queries in worker threads
- ViewModels poll job/review stats every 1 second (configurable)
- Progress updates throttled to 4/second
- Job Monitor reads from `JobQueueService.get_stats()` — no direct worker access

## Theming

Dark mode default (Catppuccin Mocha palette). Review items use semantic colors:

| Review Type | Color |
|-------------|-------|
| Unknown Artist/Album | Yellow (warning) |
| Metadata Conflict | Orange |
| Possible Duplicate | Blue (info) |
| Artwork Missing | Gray (muted) |
| Low Quality | Red (error) |

## New Dialogs

| Dialog | Purpose |
|--------|---------|
| `ReviewEditDialog` | Edit metadata before approving |
| `DuplicateCompareDialog` | Full-screen duplicate comparison |
| `RuleEditorDialog` | Visual rule builder |
| `JobDetailDialog` | Job payload, error, retry history |
| `ZoneMoveConfirmDialog` | Confirm staging → library move |

## Keyboard Shortcuts (new)

| Shortcut | Action |
|----------|--------|
| `Ctrl+R` | Open Review Queue |
| `Ctrl+J` | Open Job Monitor |
| `Ctrl+Enter` | Approve selected review item |
| `Ctrl+Shift+R` | Reject selected review item |
