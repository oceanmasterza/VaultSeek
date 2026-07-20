"""Artwork browse page — cover status per album."""

from __future__ import annotations

from uuid import UUID

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from vaultseek.core.container import Container


class ArtworkPage(QWidget):
    """Album-centric artwork status (ok / low-res / missing)."""

    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._library_id: UUID | None = None

        layout = QVBoxLayout(self)
        heading = QLabel("Artwork")
        heading.setProperty("heading", True)
        layout.addWidget(heading)
        help_lbl = QLabel(
            "Cover status from the artwork cache (embedded + Cover Art Archive). "
            "Missing covers are fetched by the fetch_artwork pipeline jobs."
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
        self._missing_only = QCheckBox("Problems only")
        self._missing_only.setToolTip("Show missing and low-resolution covers only.")
        self._missing_only.toggled.connect(self.refresh)
        toolbar.addWidget(self._missing_only)
        layout.addLayout(toolbar)

        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels(
            ["Album", "Artist", "Tracks", "Status", "Source", "Size"]
        )
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self._table)

        self._status = QLabel("")
        layout.addWidget(self._status)

    def set_library(self, library_id: UUID | None) -> None:
        self._library_id = library_id
        self.refresh()

    def refresh(self) -> None:
        self._table.setRowCount(0)
        if self._library_id is None:
            self._status.setText("No library selected — create one in Settings.")
            return
        min_w = self._container.config.artwork.min_width
        min_h = self._container.config.artwork.min_height
        needle = self._search.text().strip() or None
        # Problems only = exclude ok; still include low_res + missing
        rows = self._container.artwork_repo.list_browse_for_library(
            self._library_id,
            missing_only=False,
            query=needle,
            limit=500,
            min_width=min_w,
            min_height=min_h,
        )
        if self._missing_only.isChecked():
            rows = [row for row in rows if row.status != "ok"]
        status_label = {"ok": "OK", "missing": "Missing", "low_res": "Low-res"}
        self._table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            self._table.setItem(i, 0, QTableWidgetItem(row.label))
            self._table.setItem(i, 1, QTableWidgetItem(row.artist_name or "—"))
            self._table.setItem(i, 2, QTableWidgetItem(str(row.track_count)))
            self._table.setItem(i, 3, QTableWidgetItem(status_label.get(row.status, row.status)))
            self._table.setItem(i, 4, QTableWidgetItem(row.cover_source or "—"))
            size = (
                f"{row.width}×{row.height}"
                if row.width is not None and row.height is not None
                else "—"
            )
            self._table.setItem(i, 5, QTableWidgetItem(size))
        ok = sum(1 for row in rows if row.status == "ok")
        missing = sum(1 for row in rows if row.status == "missing")
        low = sum(1 for row in rows if row.status == "low_res")
        self._status.setText(
            f"{len(rows)} album(s) · {ok} OK · {low} low-res · {missing} missing"
        )
