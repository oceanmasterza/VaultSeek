"""Albums browse page — list + cover preview + tracks."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame,
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
    QVBoxLayout,
    QWidget,
)

from vaultseek.core.container import Container
from vaultseek.gui.widgets.browse import (
    HealthColorDelegate,
    apply_album_health_style,
    apply_track_health_style,
)
from vaultseek.gui.widgets.desktop import reveal_in_explorer
from vaultseek.gui.widgets.empty_state import EmptyState
from vaultseek.models.entities.acquisition_job import AcquisitionJobType
from vaultseek.plugins.builtin.musicbrainz.provider import MusicBrainzProvider
from vaultseek.services.album_track_display import (
    album_status_for_display,
    build_album_track_rows,
)
from vaultseek.services.library_scan_actions import run_missing_scan, run_quality_upgrade_scan
from vaultseek.services.wanted import list_wanted, promote_wanted, remove_wanted


class AlbumsPage(QWidget):
    """List albums for the active library; selection shows cover + tracks."""

    navigate_requested = Signal(str)

    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._library_id: UUID | None = None
        self._filter_artist_id: UUID | None = None
        self._album_ids: list[UUID] = []
        self._track_paths: list[str] = []
        self._wanted_ids: list[UUID] = []
        self._full_cover: QPixmap | None = None

        layout = QVBoxLayout(self)
        heading = QLabel("Albums")
        heading.setProperty("heading", True)
        layout.addWidget(heading)
        help_lbl = QLabel(
            "Select an album to see its cover and tracks. Right-click for Find / Acquire. "
            "Double-click a track to reveal it in Explorer."
        )
        help_lbl.setWordWrap(True)
        help_lbl.setProperty("muted", True)
        layout.addWidget(help_lbl)

        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("Search:"))
        self._search = QLineEdit()
        self._search.setPlaceholderText("Filter by album or artist…")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self.refresh)
        toolbar.addWidget(self._search, stretch=1)
        self._filter_label = QLabel("")
        self._filter_label.setProperty("muted", True)
        toolbar.addWidget(self._filter_label)
        self._clear_filter = QPushButton("Clear filter")
        self._clear_filter.setProperty("secondary", True)
        self._clear_filter.setVisible(False)
        self._clear_filter.clicked.connect(lambda: self.set_artist_filter(None))
        toolbar.addWidget(self._clear_filter)
        find_music = QPushButton("Find music…")
        find_music.setProperty("secondary", True)
        find_music.setToolTip("Open Find & get → Find music (gap scans + Discogs).")
        find_music.clicked.connect(lambda: self.navigate_requested.emit("find"))
        toolbar.addWidget(find_music)
        layout.addLayout(toolbar)
        legend = QLabel(
            "Colors: green = complete & meets quality · orange = missing songs or below quality prefs"
        )
        legend.setProperty("muted", True)
        legend.setWordWrap(True)
        layout.addWidget(legend)

        self._empty = EmptyState(
            "No albums yet",
            "Scan Incoming to identify releases, or use Find music → Discogs to queue downloads.",
            primary_label="Scan Incoming",
            on_primary=lambda: self.navigate_requested.emit("scan"),
            secondary_label="Find music",
            on_secondary=lambda: self.navigate_requested.emit("find"),
        )
        layout.addWidget(self._empty)

        main_split = QSplitter(Qt.Orientation.Horizontal)
        self._main_split = main_split

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        list_split = QSplitter(Qt.Orientation.Vertical)
        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels(
            ["Album", "Artist", "Year", "Tracks", "Status", "Cover"]
        )
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._album_context_menu)
        self._table.itemSelectionChanged.connect(self._on_album_selected)
        HealthColorDelegate().install_on(self._table)
        list_split.addWidget(self._table)

        tracks_box = QWidget()
        tracks_layout = QVBoxLayout(tracks_box)
        tracks_layout.setContentsMargins(0, 0, 0, 0)
        self._tracks_label = QLabel("Select an album to list tracks")
        self._tracks_label.setProperty("muted", True)
        tracks_layout.addWidget(self._tracks_label)
        self._tracks = QTableWidget(0, 4)
        self._tracks.setHorizontalHeaderLabels(["Title", "Zone", "File", "Confidence"])
        self._tracks.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._tracks.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._tracks.horizontalHeader().setStretchLastSection(True)
        self._tracks.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tracks.customContextMenuRequested.connect(self._track_context_menu)
        self._tracks.doubleClicked.connect(self._reveal_track)
        HealthColorDelegate().install_on(self._tracks)
        tracks_layout.addWidget(self._tracks, stretch=1)
        list_split.addWidget(tracks_box)
        list_split.setStretchFactor(0, 2)
        list_split.setStretchFactor(1, 2)
        left_layout.addWidget(list_split)
        main_split.addWidget(left)

        cover_panel = QFrame()
        cover_panel.setProperty("dashPanel", True)
        cover_layout = QVBoxLayout(cover_panel)
        self._cover_title = QLabel("Cover")
        self._cover_title.setProperty("panelTitle", True)
        self._cover_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cover_layout.addWidget(self._cover_title)
        self._cover_meta = QLabel("Select an album")
        self._cover_meta.setProperty("muted", True)
        self._cover_meta.setWordWrap(True)
        self._cover_meta.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cover_layout.addWidget(self._cover_meta)
        self._cover_image = QLabel()
        self._cover_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._cover_image.setMinimumSize(220, 220)
        self._cover_image.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._cover_image.setScaledContents(False)
        cover_layout.addWidget(self._cover_image, stretch=1)
        self._cover_source = QLabel("")
        self._cover_source.setProperty("muted", True)
        self._cover_source.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cover_layout.addWidget(self._cover_source)
        main_split.addWidget(cover_panel)
        main_split.setStretchFactor(0, 3)
        main_split.setStretchFactor(1, 2)
        main_split.setChildrenCollapsible(False)
        layout.addWidget(main_split, stretch=1)

        wanted_box = QFrame()
        wanted_box.setProperty("dashPanel", True)
        self._wanted_box = wanted_box
        wanted_layout = QVBoxLayout(wanted_box)
        wanted_title = QLabel("Wanted")
        wanted_title.setProperty("panelTitle", True)
        wanted_layout.addWidget(wanted_title)
        wanted_help = QLabel(
            "Parked Discogs picks waiting for download. Add from Find music → Discogs → Add to Wanted."
        )
        wanted_help.setWordWrap(True)
        wanted_help.setProperty("muted", True)
        wanted_layout.addWidget(wanted_help)
        self._wanted_table = QTableWidget(0, 4)
        self._wanted_table.setHorizontalHeaderLabels(["Artist", "Album", "Year", "Source"])
        self._wanted_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._wanted_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._wanted_table.horizontalHeader().setStretchLastSection(True)
        self._wanted_table.setMaximumHeight(160)
        wanted_layout.addWidget(self._wanted_table)
        wanted_actions = QHBoxLayout()
        start_btn = QPushButton("Start download")
        start_btn.setToolTip("Promote selected Wanted items to the Wishlist and begin search.")
        start_btn.clicked.connect(self._promote_wanted_selected)
        remove_btn = QPushButton("Remove")
        remove_btn.setProperty("secondary", True)
        remove_btn.clicked.connect(self._remove_wanted_selected)
        find_discogs = QPushButton("Find music…")
        find_discogs.setProperty("secondary", True)
        find_discogs.clicked.connect(lambda: self.navigate_requested.emit("find_discogs"))
        wanted_actions.addWidget(start_btn)
        wanted_actions.addWidget(remove_btn)
        wanted_actions.addWidget(find_discogs)
        wanted_actions.addStretch(1)
        wanted_layout.addLayout(wanted_actions)
        self._wanted_empty = QLabel("No Wanted items — add releases from Discogs browse.")
        self._wanted_empty.setProperty("muted", True)
        wanted_layout.addWidget(self._wanted_empty)
        layout.addWidget(wanted_box)

        self._status = QLabel("")
        layout.addWidget(self._status)
        self._clear_cover()
        self._empty.setVisible(False)

    def set_library(self, library_id: UUID | None) -> None:
        self._library_id = library_id
        self.refresh()

    def set_artist_filter(self, artist_id: UUID | None) -> None:
        self._filter_artist_id = artist_id
        if artist_id is None:
            self._filter_label.setText("")
            self._clear_filter.setVisible(False)
        else:
            artist = self._container.artist_repo.get(artist_id)
            name = artist.name if artist else str(artist_id)
            self._filter_label.setText(f"Filtered: {name}")
            self._clear_filter.setVisible(True)
        self.refresh()

    def refresh(self) -> None:
        self._table.setRowCount(0)
        self._album_ids = []
        self._tracks.setRowCount(0)
        self._track_paths = []
        self._tracks_label.setText("Select an album to list tracks")
        self._clear_cover()
        if self._library_id is None:
            self._status.setText("No library selected — create one in Settings.")
            self._empty.setVisible(True)
            self._main_split.setVisible(False)
            self._wanted_box.setVisible(False)
            return
        self._wanted_box.setVisible(True)
        self._reload_wanted()
        needle = self._search.text().strip() or None
        rows = self._container.album_repo.list_for_library(
            self._library_id,
            artist_id=self._filter_artist_id,
            query=needle,
            limit=500,
        )
        empty = len(rows) == 0
        self._empty.setVisible(empty and not self._wanted_ids)
        self._main_split.setVisible(not empty)
        if empty:
            self._status.setText("0 album(s)")
            return
        self._table.setRowCount(len(rows))
        prefs = self._container.config.acquisition
        for i, row in enumerate(rows):
            self._album_ids.append(row.album_id)
            tracks = self._container.track_repo.list_by_album(
                self._library_id, row.album_id, limit=500
            )
            album = self._container.album_repo.get(row.album_id)
            status = album_status_for_display(
                row.album_id,
                tracks,
                prefs=prefs,
                expected_count=row.expected_track_count
                or (album.track_count if album and album.track_count else None),
            )
            track_label = str(row.track_count)
            if status.expected_count is not None:
                track_label = f"{status.present_count}/{status.expected_count}"
            cells = [
                QTableWidgetItem(row.title),
                QTableWidgetItem(row.artist_name or "—"),
                QTableWidgetItem(str(row.year) if row.year else "—"),
                QTableWidgetItem(track_label),
                QTableWidgetItem(status.health.value.replace("_", " ")),
                QTableWidgetItem("Yes" if row.has_cover else "Missing"),
            ]
            for col, item in enumerate(cells):
                apply_album_health_style(item, status.health)
                self._table.setItem(i, col, item)
        self._status.setText(f"{len(rows)} album(s) · {len(self._wanted_ids)} wanted")

    def _reload_wanted(self) -> None:
        self._wanted_ids = []
        self._wanted_table.setRowCount(0)
        if self._library_id is None:
            return
        artist_name = None
        if self._filter_artist_id is not None:
            artist = self._container.artist_repo.get(self._filter_artist_id)
            artist_name = artist.name if artist else None
        jobs = list_wanted(
            self._container.acquisition_engine,
            self._library_id,
            artist=artist_name,
        )
        self._wanted_empty.setVisible(len(jobs) == 0)
        self._wanted_table.setVisible(len(jobs) > 0)
        self._wanted_table.setRowCount(len(jobs))
        for index, job in enumerate(jobs):
            self._wanted_ids.append(job.id)
            source = str(job.extra.get("source") or "wanted")
            self._wanted_table.setItem(index, 0, QTableWidgetItem(job.artist or ""))
            self._wanted_table.setItem(index, 1, QTableWidgetItem(job.album or ""))
            self._wanted_table.setItem(
                index, 2, QTableWidgetItem(str(job.year) if job.year else "")
            )
            self._wanted_table.setItem(index, 3, QTableWidgetItem(source))

    def _selected_wanted_ids(self) -> list[UUID]:
        rows = {index.row() for index in self._wanted_table.selectedIndexes()}
        return [self._wanted_ids[row] for row in sorted(rows) if 0 <= row < len(self._wanted_ids)]

    def _promote_wanted_selected(self) -> None:
        ids = self._selected_wanted_ids()
        if not ids:
            QMessageBox.information(self, "Wanted", "Select one or more Wanted rows.")
            return
        engine = self._container.acquisition_engine
        for job_id in ids:
            promote_wanted(engine, job_id)
        QMessageBox.information(
            self,
            "Wanted",
            f"Started download for {len(ids)} item(s). Open Wishlist to watch progress.",
        )
        self.refresh()
        self.navigate_requested.emit("acquisition")

    def _remove_wanted_selected(self) -> None:
        ids = self._selected_wanted_ids()
        if not ids:
            QMessageBox.information(self, "Wanted", "Select one or more Wanted rows.")
            return
        engine = self._container.acquisition_engine
        for job_id in ids:
            remove_wanted(engine, job_id)
        self.refresh()

    def _musicbrainz(self) -> MusicBrainzProvider | None:
        for provider in self._container.plugin_manager.get_metadata_providers():
            if isinstance(provider, MusicBrainzProvider):
                return provider
        return None

    def _selected_album_id(self) -> UUID | None:
        rows = {index.row() for index in self._table.selectedIndexes()}
        if len(rows) != 1:
            return None
        row = next(iter(rows))
        if 0 <= row < len(self._album_ids):
            return self._album_ids[row]
        return None

    def _on_album_selected(self) -> None:
        album_id = self._selected_album_id()
        if album_id is None or self._library_id is None:
            self._clear_cover()
            return
        tracks = self._container.track_repo.list_by_album(
            self._library_id, album_id, limit=500
        )
        album = self._container.album_repo.get(album_id)
        title = album.title if album else "Album"
        prefs = self._container.config.acquisition
        display_rows = build_album_track_rows(
            album=album,
            present=tracks,
            prefs=prefs,
            musicbrainz=self._musicbrainz(),
        )
        missing = sum(1 for row in display_rows if row.health.value == "missing")
        self._tracks_label.setText(
            f"Tracks on {title} ({len(display_rows)}"
            + (f", {missing} missing" if missing else "")
            + ")"
        )
        self._tracks.setRowCount(len(display_rows))
        self._track_paths = []
        for index, row in enumerate(display_rows):
            self._track_paths.append(row.file_path or "")
            cells = [
                QTableWidgetItem(row.title),
                QTableWidgetItem(row.zone),
                QTableWidgetItem(row.file_label),
                QTableWidgetItem(row.confidence),
            ]
            for col, item in enumerate(cells):
                apply_track_health_style(item, row.health)
                self._tracks.setItem(index, col, item)
        self._show_cover(album_id, title)

    def _scan_missing(self) -> None:
        if self._library_id is None:
            QMessageBox.information(self, "Albums", "Select a library first.")
            return
        count = run_missing_scan(self._container, self._library_id)
        QMessageBox.information(
            self,
            "Find missing songs",
            f"Created {count} acquisition job(s). Check Find music / Wishlist.",
        )
        self.refresh()
        if count:
            self.navigate_requested.emit("acquisition")

    def _scan_upgrades(self) -> None:
        if self._library_id is None:
            QMessageBox.information(self, "Albums", "Select a library first.")
            return
        count = run_quality_upgrade_scan(self._container, self._library_id)
        QMessageBox.information(
            self,
            "Find quality upgrades",
            f"Created {count} upgrade job(s). Check Find music / Wishlist.",
        )
        self.refresh()
        if count:
            self.navigate_requested.emit("acquisition")

    def _album_context_menu(self, pos: object) -> None:
        album_id = self._selected_album_id()
        menu = QMenu(self)
        act_find = menu.addAction("Find missing songs (library)")
        act_upgrades = menu.addAction("Find quality upgrades (library)")
        act_queue = menu.addAction("Queue this album for download")
        act_find_page = menu.addAction("Open Find music…")
        chosen = menu.exec(self._table.mapToGlobal(pos))  # type: ignore[arg-type]
        if chosen is act_find:
            self._scan_missing()
        elif chosen is act_upgrades:
            self._scan_upgrades()
        elif chosen is act_queue and album_id is not None:
            self._queue_album_download(album_id)
        elif chosen is act_find_page:
            self.navigate_requested.emit("find")

    def _track_context_menu(self, pos: object) -> None:
        menu = QMenu(self)
        act_reveal = menu.addAction("Reveal in Explorer")
        act_find = menu.addAction("Find missing songs (library)")
        act_upgrades = menu.addAction("Find quality upgrades (library)")
        act_find_page = menu.addAction("Open Find music…")
        chosen = menu.exec(self._tracks.mapToGlobal(pos))  # type: ignore[arg-type]
        if chosen is act_reveal:
            self._reveal_track()
        elif chosen is act_find:
            self._scan_missing()
        elif chosen is act_upgrades:
            self._scan_upgrades()
        elif chosen is act_find_page:
            self.navigate_requested.emit("find")

    def _queue_album_download(self, album_id: UUID) -> None:
        if self._library_id is None:
            return
        album = self._container.album_repo.get(album_id)
        if album is None:
            return
        artist_name = ""
        if album.album_artist_id is not None:
            artist = self._container.artist_repo.get(album.album_artist_id)
            artist_name = artist.name if artist else ""
        job = self._container.acquisition_engine.create_job(
            library_id=self._library_id,
            job_type=AcquisitionJobType.MISSING_ALBUM,
            artist=artist_name or None,
            album=album.title,
            year=album.year,
            mb_release_id=album.mbid,
            preferred_codec=self._container.config.acquisition.preferred_codec or None,
            priority=80,
        )
        if self._container.config.acquisition.auto_queue_jobs:
            self._container.acquisition_engine.queue(job.id)
        QMessageBox.information(
            self,
            "Albums",
            f"Queued “{album.title}” for download. Open Wishlist to acquire.",
        )
        self.navigate_requested.emit("acquisition")

    def _show_cover(self, album_id: UUID, title: str) -> None:
        self._cover_title.setText(title)
        art = self._container.artwork_repo.get_primary_for_album(album_id)
        if art is None or not art.file_path:
            self._cover_meta.setText("No cover on file for this album")
            self._cover_image.clear()
            self._cover_image.setText("No cover")
            self._cover_source.setText("")
            return
        path = Path(art.file_path)
        if not path.is_file():
            self._cover_meta.setText("Cover path missing from cache")
            self._cover_image.clear()
            self._cover_image.setText("Missing file")
            self._cover_source.setText(art.file_path)
            return
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            self._cover_meta.setText("Could not decode cover image")
            self._cover_image.clear()
            self._cover_image.setText("Invalid image")
            self._cover_source.setText(str(path))
            return
        self._cover_meta.setText(f"{art.width}×{art.height}")
        self._cover_source.setText(f"{art.source} · {path.name}")
        self._cover_image.setText("")
        self._set_scaled_cover(pixmap)

    def _set_scaled_cover(self, pixmap: QPixmap) -> None:
        size = self._cover_image.size()
        if size.width() < 40 or size.height() < 40:
            size = self._cover_image.minimumSize()
        scaled = pixmap.scaled(
            size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._cover_image.setPixmap(scaled)
        self._full_cover = pixmap

    def resizeEvent(self, event: object) -> None:  # noqa: N802 - Qt
        super().resizeEvent(event)  # type: ignore[misc]
        if self._full_cover is not None and not self._full_cover.isNull():
            self._set_scaled_cover(self._full_cover)

    def _clear_cover(self) -> None:
        self._cover_title.setText("Cover")
        self._cover_meta.setText("Select an album")
        self._cover_image.clear()
        self._cover_image.setText("")
        self._full_cover = None
        self._cover_source.setText("")

    def _reveal_track(self) -> None:
        rows = {index.row() for index in self._tracks.selectedIndexes()}
        if len(rows) != 1:
            return
        row = next(iter(rows))
        if 0 <= row < len(self._track_paths):
            path = self._track_paths[row]
            if path:
                reveal_in_explorer(path)
