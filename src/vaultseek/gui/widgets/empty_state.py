"""Reusable empty-state panel with one primary CTA (and optional secondary)."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget


class EmptyState(QWidget):
    """Centered message shown when a browse/operate table has nothing useful yet.

    Keeps first-time users moving: one clear action instead of a blank table.
    """

    def __init__(
        self,
        title: str,
        body: str,
        *,
        primary_label: str | None = None,
        on_primary: Callable[[], None] | None = None,
        secondary_label: str | None = None,
        on_secondary: Callable[[], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setProperty("dashPanel", True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 28, 24, 28)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        heading = QLabel(title)
        heading.setProperty("panelTitle", True)
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        heading.setWordWrap(True)
        layout.addWidget(heading)

        text = QLabel(body)
        text.setProperty("muted", True)
        text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        text.setWordWrap(True)
        layout.addWidget(text)

        if primary_label or secondary_label:
            row = QHBoxLayout()
            row.addStretch(1)
            if primary_label and on_primary is not None:
                primary = QPushButton(primary_label)
                primary.clicked.connect(on_primary)
                row.addWidget(primary)
            if secondary_label and on_secondary is not None:
                secondary = QPushButton(secondary_label)
                secondary.setProperty("secondary", True)
                secondary.clicked.connect(on_secondary)
                row.addWidget(secondary)
            row.addStretch(1)
            layout.addLayout(row)
