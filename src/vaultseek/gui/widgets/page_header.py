"""Shared page heading + muted help used by browse and system views."""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QLayout, QVBoxLayout


def add_page_header(
    layout: QVBoxLayout | QLayout,
    title: str,
    help_text: str | None = None,
) -> QLabel:
    """Add a consistent heading (and optional muted help) to a page layout."""
    heading = QLabel(title)
    heading.setProperty("heading", True)
    layout.addWidget(heading)
    if help_text:
        help_lbl = QLabel(help_text)
        help_lbl.setWordWrap(True)
        help_lbl.setProperty("muted", True)
        layout.addWidget(help_lbl)
    return heading
