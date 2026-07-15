# 06 — GUI Architecture

## Pattern: Model-View-ViewModel (MVVM)

MusicVault uses MVVM to strictly separate presentation from business logic.

```
┌──────────┐     signals      ┌──────────────┐     calls     ┌──────────────────┐
│  View    │ ◄────────────── │  ViewModel   │ ────────────► │ Application      │
│ (QWidget)│ ──────────────► │ (QObject)    │ ◄──────────── │ Services         │
└──────────┘   user actions   └──────────────┘   DTOs/data   └──────────────────┘
                                     │
                                     │ dispatches
                                     ▼
                              ┌──────────────┐
                              │ Worker       │
                              │ (QRunnable)  │
                              └──────────────┘
```

### Rules

1. **Views** are dumb — they only render data and forward user input to ViewModels
2. **ViewModels** hold presentation state, call services, emit signals for view updates
3. **Views never import** from `infrastructure/` or `plugins/`
4. **ViewModels never import** from `gui/views/` or `PySide6.QtWidgets`
5. Long-running work runs in **Workers** (QThreadPool), never on the main thread

## Application Shell

### Main Window Layout

```
┌─────────────────────────────────────────────────────────────┐
│  MusicVault                                    [─] [□] [×]  │
├──────────┬──────────────────────────────────────────────────┤
│          │                                                  │
│ Dashboard│              Content Area                        │
│ Library  │         (swappable view widgets)                 │
│ Artists  │                                                  │
│ Albums   │                                                  │
│ Duplicat.│                                                  │
│ Unknown  │                                                  │
│ Artwork  │                                                  │
│ Reports  │                                                  │
│ Logs     │                                                  │
│ Settings │                                                  │
│ Plugins  │                                                  │
│          │                                                  │
├──────────┴──────────────────────────────────────────────────┤
│  Status Bar: Scan progress | Track count | Last scan time   │
└─────────────────────────────────────────────────────────────┘
```

- **Sidebar navigation** — `QListWidget` or custom `NavigationPanel` widget
- **Content area** — `QStackedWidget` holding one view per page
- **Status bar** — global progress, library stats, connection status

### Navigation

```python
class MainWindow(QMainWindow):
    def __init__(self, container: Container) -> None:
        self._viewmodels = {
            "dashboard": DashboardViewModel(container),
            "library": LibraryViewModel(container),
            # ...
        }
        self._views = {
            "dashboard": DashboardView(self._viewmodels["dashboard"]),
            "library": LibraryView(self._viewmodels["library"]),
            # ...
        }
        self._stack = QStackedWidget()
        for view in self._views.values():
            self._stack.addWidget(view)
```

## ViewModels

### Base ViewModel

```python
class BaseViewModel(QObject):
    """Common functionality for all ViewModels."""

    error_occurred = Signal(str)
    loading_changed = Signal(bool)

    def __init__(self, container: Container) -> None:
        super().__init__()
        self._container = container
        self._loading = False

    @property
    def is_loading(self) -> bool:
        return self._loading

    def _set_loading(self, loading: bool) -> None:
        self._loading = loading
        self.loading_changed.emit(loading)

    def _handle_error(self, error: Exception) -> None:
        logger.error(f"ViewModel error: {error}")
        self.error_occurred.emit(str(error))
```

### Dashboard ViewModel

```python
class DashboardViewModel(BaseViewModel):
    stats_updated = Signal(LibraryStatsDTO)
    scan_history_updated = Signal(list)

    def __init__(self, container: Container) -> None:
        super().__init__(container)
        self._report_service = container.report_service

    def load_dashboard(self, library_id: int) -> None:
        self._set_loading(True)
        worker = DashboardWorker(self._report_service, library_id)
        worker.stats_ready.connect(self._on_stats_ready)
        worker.finished.connect(lambda: self._set_loading(False))
        QThreadPool.globalInstance().start(worker)

    def _on_stats_ready(self, stats: LibraryStatsDTO) -> None:
        self.stats_updated.emit(stats)
```

### Library ViewModel

```python
class LibraryViewModel(BaseViewModel):
    tracks_updated = Signal(list)       # list[TrackSummaryDTO]
    filter_changed = Signal(str)

    def load_tracks(
        self,
        library_id: int,
        *,
        offset: int = 0,
        limit: int = 100,
        search: str = "",
        sort_by: str = "artist",
    ) -> None: ...

    def start_scan(self, library_id: int, options: ScanOptions) -> None: ...
    def cancel_scan(self) -> None: ...
```

## Views

Views bind to ViewModel signals in their constructor and disconnect on destroy.

```python
class DashboardView(QWidget):
    def __init__(self, viewmodel: DashboardViewModel) -> None:
        super().__init__()
        self._vm = viewmodel
        self._setup_ui()
        self._bind_signals()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        self._stats_panel = StatsPanel()
        self._scan_history = ScanHistoryTable()
        self._progress = ProgressPanel()
        layout.addWidget(self._stats_panel)
        layout.addWidget(self._scan_history)
        layout.addWidget(self._progress)

    def _bind_signals(self) -> None:
        self._vm.stats_updated.connect(self._stats_panel.update_stats)
        self._vm.scan_history_updated.connect(self._scan_history.set_data)
        self._vm.loading_changed.connect(self._progress.set_visible)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._vm.load_dashboard(self._current_library_id)
```

### Key Views

| View | Primary Widgets | Data Source |
|------|----------------|-------------|
| `DashboardView` | Stats cards, scan history table, progress bar | `DashboardViewModel` |
| `LibraryView` | `TrackTable` (sortable, filterable), scan button | `LibraryViewModel` |
| `ArtistsView` | Artist list + album grid | `ArtistsViewModel` |
| `AlbumsView` | Album grid with artwork thumbnails | `AlbumsViewModel` |
| `DuplicatesView` | Grouped track comparison table | `DuplicatesViewModel` |
| `UnknownView` | Unidentified tracks table, identify button | `UnknownViewModel` |
| `ArtworkView` | Missing artwork grid, download/embed actions | `ArtworkViewModel` |
| `ReportsView` | Report type selector, generate button, preview | `ReportsViewModel` |
| `LogsView` | Log viewer with level filter, search | `LogsViewModel` |
| `SettingsView` | Tabbed settings (library, organize, rename, quality) | `SettingsViewModel` |
| `PluginsView` | Plugin list, enable/disable, config editor | `PluginsViewModel` |

## Workers (Background Tasks)

```python
class ScanWorker(QRunnable):
    class Signals(QObject):
        progress = Signal(ScanProgress)
        complete = Signal(ScanSession)
        error = Signal(str)

    def __init__(
        self,
        scanner_service: ScannerService,
        library_id: int,
        options: ScanOptions,
    ) -> None:
        super().__init__()
        self.signals = self.Signals()
        self._service = scanner_service
        self._library_id = library_id
        self._options = options

    def run(self) -> None:
        try:
            session = self._service.scan_library(
                self._library_id,
                self._options,
                progress_callback=lambda p: self.signals.progress.emit(p),
            )
            self.signals.complete.emit(session)
        except Exception as e:
            self.signals.error.emit(str(e))
```

### Threading Rules

| Operation | Thread | Rationale |
|-----------|--------|-----------|
| UI rendering | Main (GUI) | Qt requirement |
| Library scan | QThreadPool | CPU + I/O bound |
| Fingerprint generation | QThreadPool | CPU bound (Chromaprint) |
| Metadata lookup | QThreadPool | Network I/O |
| Database queries (read) | QThreadPool | Avoid UI freeze on large queries |
| Database writes | QThreadPool | Batch writes during scan |
| Report generation | QThreadPool | CPU + I/O |
| File move/rename | QThreadPool | I/O bound |

**Never** access Qt widgets from worker threads. Workers emit signals; ViewModels receive them on the main thread.

## Custom Widgets

### TrackTable

High-performance table for displaying thousands of tracks:

- `QTableView` with custom `TrackTableModel` (extends `QAbstractTableModel`)
- Virtual scrolling via model's `canFetchMore`/`fetchMore`
- Columns: Title, Artist, Album, Duration, Format, Quality, Path
- Sortable by any column (server-side sort via repository)
- Multi-select with checkbox column
- Context menu: Fix Metadata, Rename, Organize, Delete

### AlbumGrid

- `QListView` with custom delegate rendering artwork thumbnail + title
- Lazy image loading from artwork cache
- Placeholder icon for missing artwork

### OperationPreview

- Side-by-side diff view for pending operations
- Shows old → new for metadata, paths, artwork
- "Apply" / "Cancel" buttons
- Color-coded: green (new), red (removed), yellow (changed)

### ProgressPanel

- Multi-stage progress bar (discovering → reading → fingerprinting → saving)
- Files/second throughput counter
- ETA calculation
- Cancel button

## Theming (Dark Mode)

### Stylesheet Architecture

```
gui/resources/styles/
├── base.qss          # Shared rules (fonts, spacing)
├── dark.qss          # Dark theme colors
├── light.qss         # Light theme (future)
└── widgets/
    ├── table.qss
    ├── sidebar.qss
    └── cards.qss
```

Applied at startup:

```python
def apply_theme(app: QApplication, theme: str = "dark") -> None:
    base = read_resource("styles/base.qss")
    theme_file = read_resource(f"styles/{theme}.qss")
    app.setStyleSheet(base + theme_file)
```

### Color Palette (Dark)

| Element | Color | Usage |
|---------|-------|-------|
| Background | `#1e1e2e` | Main window, panels |
| Surface | `#2a2a3d` | Cards, tables, inputs |
| Primary | `#89b4fa` | Buttons, links, active nav |
| Text | `#cdd6f4` | Primary text |
| Text muted | `#6c7086` | Secondary text, timestamps |
| Success | `#a6e3a1` | Completed operations |
| Warning | `#f9e2af` | Warnings, unknown tracks |
| Error | `#f38ba8` | Errors, corrupt files |
| Border | `#313244` | Separators, table borders |

## Dialogs

| Dialog | Purpose | Trigger |
|--------|---------|---------|
| `ScanDialog` | Configure scan options (full/incremental, paths) | Library → Scan |
| `MetadataFixDialog` | Preview metadata changes before applying | Track context menu |
| `OrganizePreviewDialog` | Preview folder moves | Organize action |
| `DuplicateResolveDialog` | Choose which duplicate to keep | Duplicates page |
| `ConfirmOperationDialog` | Generic confirmation for destructive ops | Any mutating action |
| `SettingsDialog` | Tabbed settings editor | Settings page |
| `PluginConfigDialog` | Per-plugin configuration form | Plugins page |
| `AboutDialog` | Version, license, credits | Help menu |

## State Management

ViewModels do **not** cache large datasets. They reload from services on each page visit:

```
User navigates to Library
  → LibraryView.showEvent()
    → LibraryViewModel.load_tracks(library_id, offset=0, limit=100)
      → TrackRepository.get_by_library() (in worker thread)
        → Signal: tracks_updated(dtos)
          → TrackTable.set_data(dtos)
```

For pagination, `TrackTable` calls `viewmodel.load_tracks(offset=N)` on scroll.

### Active Library

The currently selected library is stored in a `SessionState` object (not global — injected via container):

```python
@dataclass
class SessionState:
    active_library_id: int | None = None
    active_scan_session_id: int | None = None
```

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl+1` – `Ctrl+0` | Navigate to sidebar pages |
| `Ctrl+F` | Focus search bar |
| `Ctrl+Shift+S` | Start scan |
| `Ctrl+Z` | Undo last operation |
| `Delete` | Safe-delete selected tracks |
| `F5` | Refresh current view |
| `Ctrl+,` | Open settings |

## Accessibility

- All interactive elements have accessible names
- Keyboard navigation for all views
- High-contrast theme option (future)
- Screen reader labels on icon-only buttons

## GUI Testing Strategy

GUI tests use `pytest-qt` minimally — focus on ViewModel unit tests:

```python
def test_dashboard_loads_stats(container, qtbot):
    vm = DashboardViewModel(container)
    with qtbot.waitSignal(vm.stats_updated, timeout=5000):
        vm.load_dashboard(library_id=1)
```

Full GUI integration tests are manual during development; automated E2E is Phase 14.
