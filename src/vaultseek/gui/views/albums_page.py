"""Albums browse page — list + cover preview + tracks."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from vaultseek.core.container import Container
from vaultseek.gui.widgets.browse import fill_track_table
from vaultseek.gui.widgets.desktop import reveal_in_explorer


class AlbumsPage(QWidget):
    """List albums for the active library; selection shows cover + tracks."""

    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._library_id: UUID | None = None
        self._filter_artist_id: UUID | None = None
        self._album_ids: list[UUID] = []
        self._track_paths: list[str] = []
        self._full_cover: QPixmap | None = None

        layout = QVBoxLayout(self)
        heading = QLabel("Albums")
        heading.setProperty("heading", True)
        layout.addWidget(heading)
        help_lbl = QLabel(
            "Select an album to see its cover and tracks. Double-click a track "
            "to reveal it in Explorer."
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
        layout.addLayout(toolbar)

        main_split = QSplitter(Qt.Orientation.Horizontal)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        list_split = QSplitter(Qt.Orientation.Vertical)
        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(
            ["Album", "Artist", "Year", "Tracks", "Cover"]
        )
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.itemSelectionChanged.connect(self._on_album_selected)
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
        self._tracks.doubleClicked.connect(self._reveal_track)
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

        self._status = QLabel("")
        layout.addWidget(self._status)
        self._clear_cover()

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
            return
        needle = self._search.text().strip() or None
        rows = self._container.album_repo.list_for_library(
            self._library_id,
            artist_id=self._filter_artist_id,
            query=needle,
            limit=500,
        )
        self._table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            self._album_ids.append(row.album_id)
            self._table.setItem(i, 0, QTableWidgetItem(row.title))
            self._table.setItem(i, 1, QTableWidgetItem(row.artist_name or "—"))
            self._table.setItem(i, 2, QTableWidgetItem(str(row.year) if row.year else "—"))
            self._table.setItem(i, 3, QTableWidgetItem(str(row.track_count)))
            self._table.setItem(i, 4, QTableWidgetItem("Yes" if row.has_cover else "Missing"))
        self._status.setText(f"{len(rows)} album(s)")

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
        self._tracks_label.setText(f"Tracks on {title} ({len(tracks)})")
        self._track_paths = fill_track_table(
            self._tracks, tracks, columns=("Title", "Zone", "File", "Confidence")
        )
        self._show_cover(album_id, title)

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
            reveal_in_explorer(self._track_paths[row])
