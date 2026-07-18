"""Library browse page — tracks by zone."""

from __future__ import annotations

from uuid import UUID

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from musicvault.core.container import Container
from musicvault.models.entities.track import LibraryZone


class LibraryPage(QWidget):
    """Lists tracks for the selected library, filtered by zone tab."""

    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._library_id: UUID | None = None

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
        self._zone.currentIndexChanged.connect(self.refresh)
        toolbar.addWidget(self._zone)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)

        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(["Title", "Zone", "File", "Confidence", "Quality"])
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self._table)

        self._counts = QLabel("")
        layout.addWidget(self._counts)

    def set_library(self, library_id: UUID | None) -> None:
        self._library_id = library_id
        self.refresh()

    def refresh(self) -> None:
        self._table.setRowCount(0)
        if self._library_id is None:
            self._counts.setText("No library selected — create one in Settings.")
            return

        zone = self._zone.currentData()
        tracks = self._container.track_repo.get_by_library(self._library_id, zone=zone, limit=500)
        self._table.setRowCount(len(tracks))
        for row, track in enumerate(tracks):
            self._table.setItem(row, 0, QTableWidgetItem(track.title or "(untitled)"))
            self._table.setItem(row, 1, QTableWidgetItem(track.zone.value))
            self._table.setItem(row, 2, QTableWidgetItem(track.file_name or track.file_path))
            conf = (
                f"{track.overall_confidence:.0%}" if track.overall_confidence is not None else "—"
            )
            self._table.setItem(row, 3, QTableWidgetItem(conf))
            quality = str(track.quality_score) if track.quality_score is not None else "—"
            item = QTableWidgetItem(quality)
            item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self._table.setItem(row, 4, item)

        counts = self._container.track_repo.count_by_zone(self._library_id)
        parts = [f"{name}: {count}" for name, count in sorted(counts.items())]
        self._counts.setText(f"{len(tracks)} shown · " + (" · ".join(parts) if parts else "empty"))
