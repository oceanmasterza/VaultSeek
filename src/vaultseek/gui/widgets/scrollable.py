"""Reusable vertical scroll wrapper for tall settings-style pages."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QScrollArea, QVBoxLayout, QWidget


def wrap_scrollable(page: QWidget, body: QWidget) -> QScrollArea:
    """Put ``body`` inside a frame-less scroll area filling ``page``.

    Installs a zero-margin layout on ``page`` and returns the scroll area
    (already parented). Build all form content on ``body`` afterward.
    """
    root = QVBoxLayout(page)
    root.setContentsMargins(0, 0, 0, 0)
    root.setSpacing(0)

    scroll = QScrollArea(page)
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    scroll.setWidget(body)
    root.addWidget(scroll)
    return scroll
