"""Compact integration tiles for the Dashboard."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QFrame, QLabel, QSizePolicy, QVBoxLayout, QWidget

from vaultseek.services.connection_status import ToolStatus, state_label

_LOCATION_PAGE = {
    "settings": "Settings",
    "plugins": "Plugins",
}


class IntegrationStatusTile(QFrame):
    """Short name plus state. Tooltip holds the full detail; click opens the owner page."""

    activated = Signal(str)

    def __init__(self, row: ToolStatus, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._row = row
        self.setProperty("kpiCard", True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(2)
        self._name = QLabel(row.short_name or row.name)
        self._name.setWordWrap(True)
        self._name.setProperty("stageTitle", True)
        self._name.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._state = QLabel()
        self._state.setWordWrap(True)
        self._state.setProperty("muted", True)
        self._state.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(self._name)
        layout.addWidget(self._state)
        self.apply_status(row)

    def status(self) -> ToolStatus:
        return self._row

    def apply_status(self, row: ToolStatus) -> None:
        self._row = row
        label = state_label(row.state)
        short = row.short_name or row.name
        page = _LOCATION_PAGE.get(row.location, row.location)
        self._name.setText(short)
        self._state.setText(label)
        detail = f"{row.name}. {label}. {row.detail} Open {page}."
        self.setToolTip(detail)
        self.setAccessibleName(f"{short}: {label}")
        self.setAccessibleDescription(detail)
        self.setStatusTip(detail)
        width = max(
            self.fontMetrics().horizontalAdvance(short),
            self.fontMetrics().horizontalAdvance(label),
        )
        self.setMinimumWidth(max(112, width + 28))

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 — Qt API
        if event.button() == Qt.MouseButton.LeftButton:
            self.activated.emit(self._row.location)
        super().mousePressEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 — Qt API
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.activated.emit(self._row.location)
            return
        super().keyPressEvent(event)
