"""Ctrl+K jump palette — filterable list of hub pages."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)


class JumpPalette(QDialog):
    """Modal filterable page jumper. Returns the selected page key via ``selected_key``."""

    def __init__(
        self,
        destinations: list[tuple[str, str]],
        parent: QWidget | None = None,
    ) -> None:
        """``destinations`` is a list of ``(label, page_key)``."""
        super().__init__(parent)
        self.setWindowTitle("Jump to…")
        self.setModal(True)
        self.setMinimumWidth(420)
        self.setMinimumHeight(360)
        self._all = list(destinations)
        self.selected_key: str | None = None

        layout = QVBoxLayout(self)
        hint = QLabel("Type to filter · Enter to open · Esc to cancel")
        hint.setProperty("muted", True)
        layout.addWidget(hint)

        self._filter = QLineEdit()
        self._filter.setPlaceholderText("Dashboard, Find music, Settings…")
        self._filter.textChanged.connect(self._refilter)
        self._filter.returnPressed.connect(self._accept_current)
        layout.addWidget(self._filter)

        self._list = QListWidget()
        self._list.itemActivated.connect(self._accept_item)
        self._list.itemDoubleClicked.connect(self._accept_item)
        layout.addWidget(self._list, stretch=1)

        footer = QHBoxLayout()
        footer.addStretch(1)
        layout.addLayout(footer)

        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, activated=self.reject)
        # Arrow keys move selection while typing in the filter.
        QShortcut(QKeySequence(Qt.Key.Key_Down), self._filter, activated=self._move_down)
        QShortcut(QKeySequence(Qt.Key.Key_Up), self._filter, activated=self._move_up)

        self._refilter("")
        self._filter.setFocus()

    def _move_down(self) -> None:
        row = self._list.currentRow()
        if row < self._list.count() - 1:
            self._list.setCurrentRow(row + 1)

    def _move_up(self) -> None:
        row = self._list.currentRow()
        if row > 0:
            self._list.setCurrentRow(row - 1)

    def _refilter(self, text: str) -> None:
        needle = text.strip().lower()
        self._list.clear()
        for label, key in self._all:
            if needle and needle not in label.lower() and needle not in key.lower():
                continue
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, key)
            self._list.addItem(item)
        if self._list.count():
            self._list.setCurrentRow(0)

    def _accept_item(self, item: QListWidgetItem | None) -> None:
        if item is None:
            return
        key = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(key, str) and key:
            self.selected_key = key
            self.accept()

    def _accept_current(self) -> None:
        self._accept_item(self._list.currentItem())


def jump_destinations_from_hubs(
    hubs: tuple[tuple[str, tuple[tuple[str, str], ...]], ...],
) -> list[tuple[str, str]]:
    """Flatten hub → leaf into ``(\"Hub · Leaf\", key)`` labels for the palette."""
    rows: list[tuple[str, str]] = []
    for hub_label, children in hubs:
        for child_label, key in children:
            rows.append((f"{hub_label} · {child_label}", key))
    return rows
