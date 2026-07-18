"""Duplicates page — open duplicate groups for the active library."""

from __future__ import annotations

from uuid import UUID

from PySide6.QtWidgets import QLabel, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from musicvault.core.container import Container


class DuplicatesPage(QWidget):
    """Thin list of open duplicate groups (full side-by-side compare later)."""

    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._library_id: UUID | None = None

        layout = QVBoxLayout(self)
        heading = QLabel("Duplicates")
        heading.setProperty("heading", True)
        layout.addWidget(heading)

        self._hint = QLabel(
            "Open groups awaiting resolution. Use the Review queue to approve "
            "possible-duplicate items, or resolve groups via the API."
        )
        self._hint.setWordWrap(True)
        layout.addWidget(self._hint)

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["Status", "Members", "Best track", "Created"])
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self._table)

    def set_library(self, library_id: UUID | None) -> None:
        self._library_id = library_id
        self.refresh()

    def refresh(self) -> None:
        self._table.setRowCount(0)
        if self._library_id is None:
            return
        groups = self._container.duplicate_repo.list_open_by_library(self._library_id)
        self._table.setRowCount(len(groups))
        for row, group in enumerate(groups):
            self._table.setItem(row, 0, QTableWidgetItem(group.status.value))
            self._table.setItem(row, 1, QTableWidgetItem(str(group.track_count)))
            best = str(group.best_track_id) if group.best_track_id is not None else "—"
            self._table.setItem(row, 2, QTableWidgetItem(best))
            self._table.setItem(
                row, 3, QTableWidgetItem(group.detected_at.isoformat(timespec="seconds"))
            )
