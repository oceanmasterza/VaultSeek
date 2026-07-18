"""Rules page — list automation rules for the active library."""

from __future__ import annotations

from uuid import UUID

from PySide6.QtWidgets import QLabel, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from musicvault.core.container import Container


class RulesPage(QWidget):
    """Read-only rule list (visual rule builder deferred)."""

    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._library_id: UUID | None = None

        layout = QVBoxLayout(self)
        heading = QLabel("Rules")
        heading.setProperty("heading", True)
        layout.addWidget(heading)

        self._hint = QLabel(
            "Automation rules for this library. Create and edit rules via the "
            "rules API / config for now — the visual builder ships later."
        )
        self._hint.setWordWrap(True)
        layout.addWidget(self._hint)

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["Name", "Enabled", "Priority", "Updated"])
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
        rules = self._container.rule_repo.list_by_library(self._library_id)
        self._table.setRowCount(len(rules))
        for row, rule in enumerate(rules):
            self._table.setItem(row, 0, QTableWidgetItem(rule.name))
            self._table.setItem(row, 1, QTableWidgetItem("yes" if rule.enabled else "no"))
            self._table.setItem(row, 2, QTableWidgetItem(str(rule.priority)))
            self._table.setItem(
                row, 3, QTableWidgetItem(rule.updated_at.isoformat(timespec="seconds"))
            )
