"""One health-color legend for Library and Albums tables."""

from __future__ import annotations

from PySide6.QtWidgets import QLabel

# Keep the wording identical everywhere so users learn one legend.
HEALTH_LEGEND_TEXT = "Colors: green = meets quality · orange = missing file or below quality prefs"


def health_legend_label() -> QLabel:
    """Muted legend shown under Library / Albums toolbars."""
    legend = QLabel(HEALTH_LEGEND_TEXT)
    legend.setProperty("muted", True)
    legend.setWordWrap(True)
    return legend
