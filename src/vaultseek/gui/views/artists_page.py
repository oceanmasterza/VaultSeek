"""Artists browse page — DB artists linked to this library."""

from __future__ import annotations

from uuid import UUID

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from vaultseek.core.container import Container
from vaultseek.gui.widgets.browse import fill_track_table
from vaultseek.gui.widgets.desktop import reveal_in_explorer


class ArtistsPage(QWidget):
    """List artists for the active library; selecting one shows their tracks."""

    navigate_to_albums = Signal(object)  # artist_id UUID | None

    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._library_id: UUID | None = None
        self._artist_ids: list[UUID] = []
        self._track_paths: list[str] = []

        layout = QVBoxLayout(self)
        heading = QLabel("Artists")
        heading.setProperty("heading", True)
        layout.addWidget(heading)
        help_lbl = QLabel(
            "Artists created during Identify. Select a row to see tracks; "
            "double-click to open Albums filtered to that artist."
        )
        help_lbl.setWordWrap(True)
        help_lbl.setProperty("muted", True)
        layout.addWidget(help_lbl)

        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("Search:"))
        self._search = QLineEdit()
        self._search.setPlaceholderText("Filter by artist name…")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self.refresh)
        toolbar.addWidget(self._search, stretch=1)
        layout.addLayout(toolbar)

        splitter = QSplitter(Qt.Orientation.Vertical)
        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["Artist", "Albums", "Tracks", "MBID"])
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.itemSelectionChanged.connect(self._on_artist_selected)
        self._table.doubleClicked.connect(self._open_albums)
        splitter.addWidget(self._table)

        tracks_box = QWidget()
        tracks_layout = QVBoxLayout(tracks_box)
        tracks_layout.setContentsMargins(0, 0, 0, 0)
        self._tracks_label = QLabel("Select an artist to list tracks")
        self._tracks_label.setProperty("muted", True)
        tracks_layout.addWidget(self._tracks_label)
        self._tracks = QTableWidget(0, 4)
        self._tracks.setHorizontalHeaderLabels(["Title", "Zone", "File", "Confidence"])
        self._tracks.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._tracks.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._tracks.horizontalHeader().setStretchLastSection(True)
        self._tracks.doubleClicked.connect(self._reveal_track)
        tracks_layout.addWidget(self._tracks)
        splitter.addWidget(tracks_box)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        layout.addWidget(splitter)

        self._status = QLabel("")
        layout.addWidget(self._status)

    def set_library(self, library_id: UUID | None) -> None:
        self._library_id = library_id
        self.refresh()

    def refresh(self) -> None:
        self._table.setRowCount(0)
        self._artist_ids = []
        self._tracks.setRowCount(0)
        self._track_paths = []
        self._tracks_label.setText("Select an artist to list tracks")
        if self._library_id is None:
            self._status.setText("No library selected — create one in Settings.")
            return
        needle = self._search.text().strip() or None
        rows = self._container.artist_repo.list_for_library(
            self._library_id, query=needle, limit=500
        )
        self._table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            self._artist_ids.append(row.artist_id)
            self._table.setItem(i, 0, QTableWidgetItem(row.name))
            self._table.setItem(i, 1, QTableWidgetItem(str(row.album_count)))
            self._table.setItem(i, 2, QTableWidgetItem(str(row.track_count)))
            self._table.setItem(i, 3, QTableWidgetItem(row.mbid or "—"))
        self._status.setText(f"{len(rows)} artist(s)")

    def _selected_artist_id(self) -> UUID | None:
        rows = {index.row() for index in self._table.selectedIndexes()}
        if len(rows) != 1:
            return None
        row = next(iter(rows))
        if 0 <= row < len(self._artist_ids):
            return self._artist_ids[row]
        return None

    def _on_artist_selected(self) -> None:
        artist_id = self._selected_artist_id()
        if artist_id is None or self._library_id is None:
            return
        tracks = self._container.track_repo.list_by_artist(
            self._library_id, artist_id, limit=500
        )
        artist = self._container.artist_repo.get(artist_id)
        name = artist.name if artist else "Artist"
        self._tracks_label.setText(f"Tracks for {name} ({len(tracks)})")
        self._track_paths = fill_track_table(
            self._tracks, tracks, columns=("Title", "Zone", "File", "Confidence")
        )

    def _open_albums(self) -> None:
        self.navigate_to_albums.emit(self._selected_artist_id())

    def _reveal_track(self) -> None:
        rows = {index.row() for index in self._tracks.selectedIndexes()}
        if len(rows) != 1:
            return
        row = next(iter(rows))
        if 0 <= row < len(self._track_paths):
            reveal_in_explorer(self._track_paths[row])
