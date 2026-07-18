"""Placeholder page for deferred GUI surfaces."""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class StubPage(QWidget):
    """Simple “coming soon” placeholder used for pages deferred past the
    Phase 14 MVP (Artists, Albums, Artwork viewer, Reports, Logs, Plugins).
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
