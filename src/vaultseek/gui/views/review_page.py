"""Review queue page — approve / reject / defer pending items."""

from __future__ import annotations

from uuid import UUID

from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from vaultseek.core.container import Container
from vaultseek.core.exceptions import ReviewError


class ReviewPage(QWidget):
    """Human approval gate for uncertain metadata and duplicates."""

    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._library_id: UUID | None = None
        self._item_ids: list[UUID] = []

        layout = QVBoxLayout(self)
        self._heading = QLabel("Review Queue")
        self._heading.setProperty("heading", True)
        layout.addWidget(self._heading)

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["Type", "Track", "Confidence", "Reason"])
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self._table)

        buttons = QHBoxLayout()
        self._approve_btn = QPushButton("Approve")
        self._approve_btn.setDefault(True)
        self._approve_btn.setToolTip("Approve selected items (Ctrl+Enter)")
        self._reject_btn = QPushButton("Reject")
        self._reject_btn.setToolTip("Reject selected items (Ctrl+Shift+R)")
        self._defer_btn = QPushButton("Defer")
        self._refresh_btn = QPushButton("Refresh")
        self._reject_btn.setProperty("secondary", True)
        self._defer_btn.setProperty("secondary", True)
        self._refresh_btn.setProperty("secondary", True)
        self._approve_btn.clicked.connect(self._approve_selected)
        self._reject_btn.clicked.connect(self._reject_selected)
        self._defer_btn.clicked.connect(self._defer_selected)
        self._refresh_btn.clicked.connect(self.refresh)
        buttons.addWidget(self._approve_btn)
        buttons.addWidget(self._reject_btn)
        buttons.addWidget(self._defer_btn)
        buttons.addWidget(self._refresh_btn)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self._approve_selected)
        QShortcut(QKeySequence("Ctrl+Enter"), self, activated=self._approve_selected)
        QShortcut(QKeySequence("Ctrl+Shift+R"), self, activated=self._reject_selected)

    def set_library(self, library_id: UUID | None) -> None:
        self._library_id = library_id
        self.refresh()

    def refresh(self) -> None:
        self._table.setRowCount(0)
        self._item_ids = []
        if self._library_id is None:
            self._heading.setText("Review Queue")
            return

        items = list(self._container.review_queue.get_pending(self._library_id))
        self._heading.setText(f"Review Queue ({len(items)} pending)")
        self._table.setRowCount(len(items))
        for row, item in enumerate(items):
            self._item_ids.append(item.id)
            self._table.setItem(row, 0, QTableWidgetItem(item.review_type.value))
            self._table.setItem(row, 1, QTableWidgetItem(item.title))
            conf = f"{item.confidence:.0%}" if item.confidence is not None else "—"
            self._table.setItem(row, 2, QTableWidgetItem(conf))
            self._table.setItem(row, 3, QTableWidgetItem(item.description or ""))

    def pending_count(self) -> int:
        if self._library_id is None:
            return 0
        return self._container.review_queue.count_pending(self._library_id)

    def _selected_ids(self) -> list[UUID]:
        rows = {index.row() for index in self._table.selectedIndexes()}
        return [self._item_ids[row] for row in sorted(rows) if 0 <= row < len(self._item_ids)]

    def _approve_selected(self) -> None:
        self._act(self._container.review_queue.approve)

    def _reject_selected(self) -> None:
        self._act(self._container.review_queue.reject)

    def _defer_selected(self) -> None:
        self._act(self._container.review_queue.defer)

    def _act(self, action: object) -> None:
        ids = self._selected_ids()
        if not ids:
            return
        try:
            for item_id in ids:
                action(item_id)  # type: ignore[operator]
        except ReviewError as exc:
            QMessageBox.warning(self, "Review", str(exc))
        self.refresh()
