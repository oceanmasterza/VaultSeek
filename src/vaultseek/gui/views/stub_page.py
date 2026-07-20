"""Placeholder page for deferred GUI surfaces."""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class StubPage(QWidget):
    """Simple placeholder for surfaces not yet built (Reports viewer,
    Plugin manager). Most Phase 14 pages are real views now.
    """

    def __init__(self, title: str, message: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        heading = QLabel(title)
        heading.setProperty("heading", True)
        body = QLabel(message)
        body.setWordWrap(True)
        layout.addWidget(heading)
        layout.addWidget(body)
        layout.addStretch(1)
