"""Duplicates page — open duplicate groups for the active library."""

from __future__ import annotations

from uuid import UUID

from PySide6.QtWidgets import QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from vaultseek.core.container import Container
from vaultseek.gui.datetime_format import format_local_datetime
from vaultseek.gui.widgets.empty_state import EmptyState
from vaultseek.gui.widgets.page_header import add_page_header
from vaultseek.gui.widgets.table_utils import (
    configure_data_table,
)


class DuplicatesPage(QWidget):
    """Thin list of open duplicate groups (full side-by-side compare later)."""

    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._library_id: UUID | None = None

        layout = QVBoxLayout(self)
        add_page_header(
            layout,
            "Duplicates",
            "Open groups detected by the pipeline. Side-by-side compare is not built yet — "
            "possible-duplicate items also appear on Review.",
        )

        self._empty = EmptyState(
            "No open duplicate groups",
            "When the pipeline finds likely copies, they will list here.",
        )
        layout.addWidget(self._empty)

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["Status", "Members", "Best chosen", "Created"])
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        configure_data_table(self._table)
        layout.addWidget(self._table)

    def set_library(self, library_id: UUID | None) -> None:
        self._library_id = library_id
        self.refresh()

    def refresh(self) -> None:
        self._table.setRowCount(0)
        if self._library_id is None:
            self._empty.setVisible(True)
            self._table.setVisible(False)
            return
        groups = self._container.duplicate_repo.list_open_by_library(self._library_id)
        empty = len(groups) == 0
        self._empty.setVisible(empty)
        self._table.setVisible(not empty)
        if empty:
            return
        self._table.setRowCount(len(groups))
        for row, group in enumerate(groups):
            self._table.setItem(row, 0, QTableWidgetItem(group.status.value))
            self._table.setItem(row, 1, QTableWidgetItem(str(group.track_count)))
            best = "Yes" if group.best_track_id is not None else "—"
            self._table.setItem(row, 2, QTableWidgetItem(best))
            self._table.setItem(row, 3, QTableWidgetItem(format_local_datetime(group.detected_at)))
