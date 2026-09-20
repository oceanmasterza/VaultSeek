"""Albums browse page — list + cover preview + tracks."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QPixmap, QResizeEvent
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
from vaultseek.core.exceptions import OperationError
from vaultseek.gui.async_task import run_in_background
from vaultseek.gui.debounce import connect_debounced
from vaultseek.gui.widgets.browse import (
    HealthColorDelegate,
    apply_album_health_style,
    apply_track_health_style,
)
from vaultseek.gui.widgets.desktop import reveal_in_explorer
from vaultseek.gui.widgets.empty_state import EmptyState
from vaultseek.gui.widgets.health_legend import health_legend_label
from vaultseek.gui.widgets.table_utils import (
    begin_table_update,
    configure_data_table,
    end_table_update,
)
from vaultseek.models.entities.acquisition_job import AcquisitionJobType
from vaultseek.models.entities.operation import OperationType
from vaultseek.models.entities.track import LibraryZone
from vaultseek.plugins.builtin.musicbrainz.provider import MusicBrainzProvider
from vaultseek.services.album_track_display import (
    album_status_for_display,
    build_album_track_rows,
)
from vaultseek.services.dto.operation_dto import OperationRequest
from vaultseek.services.library_scan_actions import (
    run_missing_scan,
    run_missing_scan_for_album,
    run_quality_upgrade_scan,
)
from vaultseek.services.wanted import list_wanted


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
        connect_debounced(self._search.textChanged, self.refresh, parent=self)
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
        archive_album = QPushButton("Archive selected…")
        archive_album.setProperty("secondary", True)
        archive_album.setToolTip("Move all present songs on the selected album(s) to Archive.")
        archive_album.clicked.connect(self._archive_selected_albums)
        toolbar.addWidget(archive_album)
        self._delete_album = QPushButton("Delete album…")
        self._delete_album.setToolTip(
            "Remove the album from VaultSeek and recycle its music files."
        )
        self._delete_album.clicked.connect(self._delete_selected_albums)
        toolbar.addWidget(self._delete_album)
        layout.addLayout(toolbar)
        layout.addWidget(health_legend_label())

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
        configure_data_table(self._table)
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
        configure_data_table(self._tracks)
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
        self._cover_image.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
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
        wanted_layout = QHBoxLayout(wanted_box)
        wanted_layout.setContentsMargins(12, 8, 12, 8)
        self._wanted_status = QLabel("Wanted items are managed on Wishlist.")
        self._wanted_status.setProperty("muted", True)
        self._wanted_status.setWordWrap(True)
        open_wanted = QPushButton("Open Wishlist")
        open_wanted.setProperty("secondary", True)
        open_wanted.setToolTip("Parked Discogs picks live on Wishlist → Show Wanted.")
        open_wanted.clicked.connect(lambda: self.navigate_requested.emit("acquisition"))
        wanted_layout.addWidget(self._wanted_status, stretch=1)
        wanted_layout.addWidget(open_wanted)
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
        begin_table_update(self._table)
        begin_table_update(self._tracks)
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
            end_table_update(self._table)
            end_table_update(self._tracks)
            return
        self._wanted_box.setVisible(True)
        self._reload_wanted_count()
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
            end_table_update(self._table)
            end_table_update(self._tracks)
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
                list(tracks),
                prefs=prefs,
                expected_count=row.expected_track_count
                or (album.track_count if album and album.track_count else None),
            )
            track_label = str(row.track_count)
            if status.expected_count is not None:
                track_label = f"{status.present_count}/{status.expected_count}"
            year_item = QTableWidgetItem()
            year_item.setData(Qt.ItemDataRole.DisplayRole, str(row.year) if row.year else "—")
            year_item.setData(Qt.ItemDataRole.EditRole, int(row.year or 0))
            title_item = QTableWidgetItem(row.title)
            title_item.setData(Qt.ItemDataRole.UserRole, str(row.album_id))
            cells = [
                title_item,
                QTableWidgetItem(row.artist_name or "—"),
                year_item,
                QTableWidgetItem(track_label),
                QTableWidgetItem(status.health.value.replace("_", " ")),
                QTableWidgetItem("Yes" if row.has_cover else "Missing"),
            ]
            for col, item in enumerate(cells):
                apply_album_health_style(item, status.health)
                self._table.setItem(i, col, item)
        self._status.setText(f"{len(rows)} album(s)")
        end_table_update(self._table)
        end_table_update(self._tracks)

    def _reload_wanted_count(self) -> None:
        self._wanted_ids = []
        if self._library_id is None:
            self._wanted_status.setText("Wanted items are managed on Wishlist.")
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
        self._wanted_ids = [job.id for job in jobs]
        if jobs:
            self._wanted_status.setText(
                f"{len(jobs)} Wanted item(s) parked — start or remove them on Wishlist "
                "(enable Show Wanted)."
            )
        else:
            self._wanted_status.setText(
                "No Wanted items. Add releases from Find music → Discogs, then manage "
                "them on Wishlist."
            )

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
        item = self._table.item(row, 0)
        raw = item.data(Qt.ItemDataRole.UserRole) if item else None
        if raw:
            return UUID(str(raw))
        if 0 <= row < len(self._album_ids):
            return self._album_ids[row]
        return None

    def _selected_album_ids(self) -> list[UUID]:
        """Return selected album IDs in their displayed order."""
        rows = sorted({index.row() for index in self._table.selectedIndexes()})
        return [
            UUID(str(item.data(Qt.ItemDataRole.UserRole)))
            for row in rows
            if (item := self._table.item(row, 0)) is not None
            and item.data(Qt.ItemDataRole.UserRole)
        ]

    def _selected_track_ids(self) -> list[UUID]:
        """Return selected real track IDs, excluding MusicBrainz-only missing rows."""
        rows = sorted({index.row() for index in self._tracks.selectedIndexes()})
        selected: list[UUID] = []
        for row in rows:
            item = self._tracks.item(row, 0)
            track_id = item.data(Qt.ItemDataRole.UserRole + 1) if item else None
            if track_id:
                selected.append(UUID(str(track_id)))
        return selected

    def _on_album_selected(self) -> None:
        album_id = self._selected_album_id()
        if album_id is None or self._library_id is None:
            self._clear_cover()
            return
        tracks = self._container.track_repo.list_by_album(self._library_id, album_id, limit=500)
        album = self._container.album_repo.get(album_id)
        title = album.title if album else "Album"
        prefs = self._container.config.acquisition
        display_rows = build_album_track_rows(
            album=album,
            present=list(tracks),
            prefs=prefs,
            musicbrainz=self._musicbrainz(),
        )
        missing = sum(1 for row in display_rows if row.health.value == "missing")
        self._tracks_label.setText(
            f"Tracks on {title} ({len(display_rows)}"
            + (f", {missing} missing" if missing else "")
            + ")"
        )
        begin_table_update(self._tracks)
        self._tracks.setRowCount(len(display_rows))
        self._track_paths = []
        track_by_path = {track.file_path: track.id for track in tracks}
        for index, row in enumerate(display_rows):
            self._track_paths.append(row.file_path or "")
            path_item = QTableWidgetItem(row.title)
            path_item.setData(Qt.ItemDataRole.UserRole, row.file_path or "")
            track_id = track_by_path.get(row.file_path or "")
            path_item.setData(Qt.ItemDataRole.UserRole + 1, str(track_id) if track_id else None)
            cells = [
                path_item,
                QTableWidgetItem(row.zone),
                QTableWidgetItem(row.file_label),
                QTableWidgetItem(row.confidence),
            ]
            for col, item in enumerate(cells):
                apply_track_health_style(item, row.health)
                self._tracks.setItem(index, col, item)
        end_table_update(self._tracks)
        self._show_cover(album_id, title)

    def _scan_missing(self, *, album_id: UUID | None = None) -> None:
        if self._library_id is None:
            QMessageBox.information(self, "Albums", "Select a library first.")
            return
        library_id = self._library_id
        target_album = album_id
        if target_album is not None:
            self._status.setText("Finding missing songs for this album (background)…")
        else:
            self._status.setText("Scanning for missing songs (background)…")

        def work() -> int:
            if target_album is not None:
                return run_missing_scan_for_album(self._container, library_id, target_album)
            return run_missing_scan(self._container, library_id)

        def done(count: object) -> None:
            n = int(count) if isinstance(count, int) else 0
            scope = "this album" if target_album is not None else "library"
            self._status.setText(f"Created {n} missing-song job(s) for {scope}.")
            self.refresh()
            if n:
                self.navigate_requested.emit("acquisition")

        run_in_background(
            work,
            on_finished=done,
            on_failed=lambda msg: QMessageBox.warning(self, "Albums", msg),
        )

    def _scan_upgrades(self) -> None:
        if self._library_id is None:
            QMessageBox.information(self, "Albums", "Select a library first.")
            return
        library_id = self._library_id
        self._status.setText("Scanning for quality upgrades (background)…")

        def work() -> int:
            return run_quality_upgrade_scan(self._container, library_id)

        def done(count: object) -> None:
            n = int(count) if isinstance(count, int) else 0
            self._status.setText(f"Created {n} upgrade job(s).")
            self.refresh()
            if n:
                self.navigate_requested.emit("acquisition")

        run_in_background(
            work,
            on_finished=done,
            on_failed=lambda msg: QMessageBox.warning(self, "Albums", msg),
        )

    def _album_context_menu(self, pos: QPoint) -> None:
        album_id = self._selected_album_id()
        menu = QMenu(self)
        act_find = menu.addAction("Find missing songs (this album)")
        act_find_lib = menu.addAction("Find missing songs (whole library)")
        act_upgrades = menu.addAction("Find quality upgrades (library)")
        act_queue = menu.addAction("Queue this album for download")
        act_archive = menu.addAction("Archive selected album(s)…")
        act_delete = menu.addAction("Delete selected album(s)…")
        act_find_page = menu.addAction("Open Find music…")
        chosen = menu.exec(self._table.mapToGlobal(pos))
        if chosen is act_find and album_id is not None:
            self._scan_missing(album_id=album_id)
        elif chosen is act_find_lib:
            self._scan_missing()
        elif chosen is act_upgrades:
            self._scan_upgrades()
        elif chosen is act_queue and album_id is not None:
            self._queue_album_download(album_id)
        elif chosen is act_archive:
            self._archive_selected_albums()
        elif chosen is act_delete:
            self._delete_selected_albums()
        elif chosen is act_find_page:
            self.navigate_requested.emit("find")

    def _track_context_menu(self, pos: QPoint) -> None:
        album_id = self._selected_album_id()
        menu = QMenu(self)
        act_reveal = menu.addAction("Reveal in Explorer")
        act_archive = menu.addAction("Archive selected track(s)…")
        act_find = menu.addAction("Find missing songs (this album)")
        act_find_lib = menu.addAction("Find missing songs (whole library)")
        act_upgrades = menu.addAction("Find quality upgrades (library)")
        act_find_page = menu.addAction("Open Find music…")
        chosen = menu.exec(self._tracks.mapToGlobal(pos))
        if chosen is act_reveal:
            self._reveal_track()
        elif chosen is act_archive:
            self._archive_selected_tracks()
        elif chosen is act_find and album_id is not None:
            self._scan_missing(album_id=album_id)
        elif chosen is act_find_lib:
            self._scan_missing()
        elif chosen is act_upgrades:
            self._scan_upgrades()
        elif chosen is act_find_page:
            self.navigate_requested.emit("find")

    def _delete_selected_albums(self) -> None:
        if not self._delete_album.isEnabled():
            return
        album_ids = self._selected_album_ids()
        library_id = self._library_id
        if not album_ids or library_id is None:
            QMessageBox.information(self, "Delete albums", "Select one or more albums first.")
            return
        names = [
            album.title
            for aid in album_ids
            if (album := self._container.album_repo.get(aid)) is not None
        ]
        count = self._container.album_repo.count_tracks(library_id, album_ids)
        answer = QMessageBox.question(
            self,
            "Delete albums and music files",
            f"Delete these albums ({count} songs) from this library and remove their music files "
            "from all its folders, including Archive?\n\n"
            + "\n".join(names[:15])
            + (f"\n…and {len(names) - 15} more" if len(names) > 15 else "")
            + "\n\nWindows uses the Recycle Bin where supported; "
            "otherwise files may be permanently deleted. "
            "This is not Archive and cannot be undone through VaultSeek. "
            "Unrelated files in shared folders are kept.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._delete_album.setEnabled(False)

        def work() -> int:
            return sum(self._container.album_deletion.delete(library_id, aid) for aid in album_ids)

        def done(result: object) -> None:
            self._delete_album.setEnabled(True)
            self.refresh()
            self._status.setText(
                f"Deleted {result} song(s) and removed their albums from this library."
            )

        def failed(message: str) -> None:
            self._delete_album.setEnabled(True)
            self.refresh()
            QMessageBox.warning(self, "Album deletion stopped", message)

        run_in_background(work, on_finished=done, on_failed=failed)

    def _archive_selected_albums(self) -> None:
        """Queue all present files in selected albums for reversible archiving."""
        if self._library_id is None:
            return
        track_ids: list[UUID] = []
        for album_id in self._selected_album_ids():
            track_ids.extend(
                track.id
                for track in self._container.track_repo.list_by_album(
                    self._library_id, album_id, limit=100_000
                )
            )
        self._archive_tracks(track_ids, "selected album(s)")

    def _archive_selected_tracks(self) -> None:
        """Queue selected present album tracks for reversible archiving."""
        self._archive_tracks(self._selected_track_ids(), "selected track(s)")

    def _archive_tracks(self, track_ids: list[UUID], label: str) -> None:
        """Confirm and enqueue archive moves through the operation service."""
        if not track_ids:
            QMessageBox.information(self, "Archive music", f"Select {label} first.")
            return
        if self._library_id is None:
            return
        library = self._container.library_repo.get(self._library_id)
        if library is None:
            return
        answer = QMessageBox.question(
            self,
            "Archive music",
            f"Move {len(track_ids)} song(s) from {label} to:\n{library.archive_path}\n\n"
            "VaultSeek keeps an operation history so the move can be rolled back.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer is not QMessageBox.StandardButton.Yes:
            return
        queued = 0
        errors: list[str] = []
        for track_id in dict.fromkeys(track_ids):
            try:
                result = self._container.operation_orchestrator.execute(
                    OperationRequest(
                        operation_type=OperationType.FILE_MOVE,
                        track_id=track_id,
                        target_zone=LibraryZone.ARCHIVE,
                        dry_run=False,
                    )
                )
            except OperationError as exc:
                errors.append(str(exc))
            else:
                queued += result.affected_count
        self._status.setText(
            f"Queued {queued} song(s) for Archive"
            + (f"; skipped {len(errors)}." if errors else ".")
        )
        if errors:
            QMessageBox.warning(self, "Archive music", "\n".join(errors[:3]))

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
        self._status.setText(f"Queued “{album.title}” for download.")
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

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 - Qt
        super().resizeEvent(event)
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
        item = self._tracks.item(row, 0)
        path = ""
        if item is not None:
            path = str(item.data(Qt.ItemDataRole.UserRole) or "")
        if not path and 0 <= row < len(self._track_paths):
            path = self._track_paths[row]
        if path:
            reveal_in_explorer(path)
