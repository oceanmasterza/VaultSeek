"""Library browse page — folder tree + tracks by zone / path."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QVBoxLayout,
    QWidget,
)

from vaultseek.core.container import Container
from vaultseek.gui.widgets.browse import (
    HealthColorDelegate,
    apply_track_health_style,
    build_folder_tree,
)
from vaultseek.gui.widgets.desktop import copy_text_to_clipboard, open_path, reveal_in_explorer
from vaultseek.gui.widgets.empty_state import EmptyState
from vaultseek.models.entities.job import JobType
from vaultseek.models.entities.track import LibraryZone, Track
from vaultseek.services.album_track_display import effective_track_health
from vaultseek.services.library_scan_actions import run_missing_scan, run_quality_upgrade_scan


class LibraryPage(QWidget):
    """Lists tracks for the selected library with a zone folder tree."""

    navigate_requested = Signal(str)

    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._library_id: UUID | None = None
        self._file_paths: list[str] = []
        self._folder_prefix: str | None = None
        self._folder_zone: LibraryZone | None = None

        layout = QVBoxLayout(self)
        heading = QLabel("Library")
        heading.setProperty("heading", True)
        layout.addWidget(heading)

        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("Zone:"))
        self._zone = QComboBox()
        self._zone.addItem("All zones", None)
        for zone in LibraryZone:
            self._zone.addItem(zone.value.title(), zone)
        self._zone.currentIndexChanged.connect(self._on_zone_combo)
        toolbar.addWidget(self._zone)
        toolbar.addWidget(QLabel("Search:"))
        self._search = QLineEdit()
        self._search.setPlaceholderText("Filter by title or file name…")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._reload_tracks)
        toolbar.addWidget(self._search, stretch=1)
        scan_btn = QPushButton("Scan incoming")
        scan_btn.setProperty("secondary", True)
        scan_btn.setToolTip("Enqueue a scan of this library’s Incoming folder.")
        scan_btn.clicked.connect(self._scan_incoming)
        toolbar.addWidget(scan_btn)
        find_music = QPushButton("Find music…")
        find_music.setProperty("secondary", True)
        find_music.clicked.connect(lambda: self.navigate_requested.emit("find"))
        toolbar.addWidget(find_music)
        layout.addLayout(toolbar)
        legend = QLabel(
            "Colors: green = meets quality · orange = missing file or below quality prefs"
        )
        legend.setProperty("muted", True)
        layout.addWidget(legend)

        self._empty = EmptyState(
            "No tracks yet",
            "Scan Incoming to import music, or open Find music to download missing albums.",
            primary_label="Scan Incoming",
            on_primary=self._scan_incoming,
            secondary_label="Find music",
            on_secondary=lambda: self.navigate_requested.emit("find"),
        )
        layout.addWidget(self._empty)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter = splitter
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        tree_title = QLabel("Folders")
        tree_title.setProperty("panelTitle", True)
        left_layout.addWidget(tree_title)
        tree_help = QLabel("Zone roots → artist / album folders from file paths.")
        tree_help.setWordWrap(True)
        tree_help.setProperty("muted", True)
        left_layout.addWidget(tree_help)
        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setMinimumWidth(200)
        self._tree.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._tree.currentItemChanged.connect(self._on_tree_selection)
        left_layout.addWidget(self._tree, stretch=1)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(
            ["Title", "Zone", "File", "Confidence", "Quality"]
        )
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._context_menu)
        self._table.doubleClicked.connect(self._reveal_selected)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        HealthColorDelegate().install_on(self._table)
        right_layout.addWidget(self._table, stretch=1)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        splitter.setChildrenCollapsible(False)
        layout.addWidget(splitter, stretch=1)

        self._counts = QLabel("")
        layout.addWidget(self._counts)
        self._empty.setVisible(False)

        reveal = QAction("Reveal in Explorer", self)
        reveal.setShortcut(QKeySequence("Ctrl+Return"))
        reveal.triggered.connect(self._reveal_selected)
        self.addAction(reveal)

    def set_library(self, library_id: UUID | None) -> None:
        self._library_id = library_id
        self._folder_prefix = None
        self._folder_zone = None
        self.refresh()

    def refresh(self) -> None:
        self._rebuild_tree()
        self._reload_tracks()

    def _rebuild_tree(self) -> None:
        self._tree.clear()
        if self._library_id is None:
            return
        library = self._container.library_repo.get(self._library_id)
        if library is None:
            return
        paths = self._container.track_repo.list_paths_for_library(self._library_id)
        build_folder_tree(self._tree, library, paths)

    def _on_zone_combo(self) -> None:
        # Zone combo overrides folder filter when changed explicitly.
        self._folder_prefix = None
        self._folder_zone = self._zone.currentData()
        self._reload_tracks()

    def _on_tree_selection(self, current: object, _previous: object) -> None:
        if current is None:
            return
        data = current.data(0, Qt.ItemDataRole.UserRole)  # type: ignore[union-attr]
        if not isinstance(data, dict):
            return
        kind = data.get("kind")
        if kind == "all":
            self._folder_prefix = None
            self._folder_zone = None
            self._zone.blockSignals(True)
            self._zone.setCurrentIndex(0)
            self._zone.blockSignals(False)
        elif kind == "zone":
            zone_val = data.get("zone")
            self._folder_prefix = None
            self._folder_zone = LibraryZone(zone_val) if isinstance(zone_val, str) else None
            self._sync_zone_combo(self._folder_zone)
        elif kind == "folder":
            zone_val = data.get("zone")
            prefix = data.get("prefix")
            self._folder_zone = LibraryZone(zone_val) if isinstance(zone_val, str) else None
            self._folder_prefix = str(prefix) if prefix else None
            self._sync_zone_combo(self._folder_zone)
        self._reload_tracks()

    def _sync_zone_combo(self, zone: LibraryZone | None) -> None:
        self._zone.blockSignals(True)
        if zone is None:
            self._zone.setCurrentIndex(0)
        else:
            for i in range(self._zone.count()):
                if self._zone.itemData(i) is zone:
                    self._zone.setCurrentIndex(i)
                    break
        self._zone.blockSignals(False)

    def _reload_tracks(self) -> None:
        self._table.setRowCount(0)
        self._file_paths = []
        if self._library_id is None:
            self._counts.setText("No library selected — create one in Settings.")
            self._empty.setVisible(True)
            self._splitter.setVisible(False)
            return

        zone = self._folder_zone if self._folder_zone is not None else self._zone.currentData()
        needle = self._search.text().strip().lower()
        if self._folder_prefix:
            prefix = self._folder_prefix.rstrip("\\/")
            tracks = list(
                self._container.track_repo.list_by_path_prefix(
                    self._library_id,
                    prefix,
                    zone=zone,
                    limit=500,
                )
            )
        else:
            tracks = list(
                self._container.track_repo.get_by_library(
                    self._library_id, zone=zone, limit=500
                )
            )
        if needle:
            tracks = [
                track
                for track in tracks
                if needle in (track.title or "").lower()
                or needle in (track.file_name or "").lower()
                or needle in (track.file_path or "").lower()
            ]
        empty = (
            len(tracks) == 0
            and not needle
            and self._folder_prefix is None
            and self._zone.currentData() is None
            and self._folder_zone is None
        )
        # Show empty CTA only for truly empty libraries (not filter misses).
        self._empty.setVisible(empty)
        self._splitter.setVisible(not empty)
        if empty:
            self._counts.setText("0 tracks")
            return

        self._fill_table(tracks)

        counts = self._container.track_repo.count_by_zone(self._library_id)
        parts = [f"{name}: {count}" for name, count in sorted(counts.items())]
        folder_note = ""
        if self._folder_prefix:
            folder_note = f" · folder: {Path(self._folder_prefix).name}"
        self._counts.setText(
            f"{len(tracks)} shown{folder_note} · "
            + (" · ".join(parts) if parts else "empty")
        )

    def _fill_table(self, tracks: list[Track]) -> None:
        self._table.setRowCount(len(tracks))
        self._file_paths = []
        prefs = self._container.config.acquisition
        for row, track in enumerate(tracks):
            self._file_paths.append(track.file_path)
            conf = (
                f"{track.overall_confidence:.0%}"
                if track.overall_confidence is not None
                else "—"
            )
            quality = str(track.quality_score) if track.quality_score is not None else "—"
            cells = [
                QTableWidgetItem(track.title or "(untitled)"),
                QTableWidgetItem(track.zone.value),
                QTableWidgetItem(track.file_name or track.file_path),
                QTableWidgetItem(conf),
                QTableWidgetItem(quality),
            ]
            cells[4].setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            health = effective_track_health(track, prefs)
            for col, item in enumerate(cells):
                apply_track_health_style(item, health)
                self._table.setItem(row, col, item)

    def _scan_missing(self) -> None:
        if self._library_id is None:
            QMessageBox.warning(self, "Library", "Select or create a library in Settings first.")
            return
        count = run_missing_scan(self._container, self._library_id)
        QMessageBox.information(
            self,
            "Find missing songs",
            f"Created {count} acquisition job(s). Check Find music / Wishlist.",
        )
        if count:
            self.navigate_requested.emit("acquisition")

    def _scan_upgrades(self) -> None:
        if self._library_id is None:
            QMessageBox.warning(self, "Library", "Select or create a library in Settings first.")
            return
        count = run_quality_upgrade_scan(self._container, self._library_id)
        QMessageBox.information(
            self,
            "Find quality upgrades",
            f"Created {count} upgrade job(s). Check Find music / Wishlist.",
        )
        if count:
            self.navigate_requested.emit("acquisition")

    def _selected_path(self) -> str | None:
        rows = {index.row() for index in self._table.selectedIndexes()}
        if len(rows) != 1:
            return None
        row = next(iter(rows))
        if 0 <= row < len(self._file_paths):
            return self._file_paths[row]
        return None

    def _context_menu(self, pos: object) -> None:
        menu = QMenu(self)
        path = self._selected_path()
        act_reveal = menu.addAction("Reveal in Explorer")
        act_copy = menu.addAction("Copy path")
        act_open = menu.addAction("Open containing folder")
        menu.addSeparator()
        act_find = menu.addAction("Find missing songs (library)")
        act_upgrades = menu.addAction("Find quality upgrades (library)")
        act_find_page = menu.addAction("Open Find music…")
        if not path:
            act_reveal.setEnabled(False)
            act_copy.setEnabled(False)
            act_open.setEnabled(False)
        chosen = menu.exec(self._table.viewport().mapToGlobal(pos))  # type: ignore[arg-type]
        if chosen is act_reveal and path:
            reveal_in_explorer(path)
        elif chosen is act_copy and path:
            copy_text_to_clipboard(path)
        elif chosen is act_open and path:
            open_path(Path(path).parent)
        elif chosen is act_find:
            self._scan_missing()
        elif chosen is act_upgrades:
            self._scan_upgrades()
        elif chosen is act_find_page:
            self.navigate_requested.emit("find")

    def _reveal_selected(self, *_args: object) -> None:
        path = self._selected_path()
        if path:
            reveal_in_explorer(path)

    def _scan_incoming(self) -> None:
        if self._library_id is None:
            QMessageBox.warning(self, "Library", "Select or create a library in Settings first.")
            return
        library = self._container.library_repo.get(self._library_id)
        if library is None:
            return
        stats = self._container.job_queue.get_stats(library.id)
        if stats.by_type.get(JobType.SCAN_DIRECTORY.value, 0) > 0:
            QMessageBox.information(self, "Library", "A scan is already queued for this library.")
            return
        self._container.job_queue.enqueue(
            JobType.SCAN_DIRECTORY,
            library.id,
            {
                "directory": library.incoming_path,
                "zone": LibraryZone.INCOMING.value,
            },
        )
        QMessageBox.information(self, "Library", f"Scan queued for:\n{library.incoming_path}")
