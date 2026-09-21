"""Keep numeric editors at the width of their values, not the form."""

from __future__ import annotations

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QAbstractSpinBox, QSizePolicy, QWidget

_REFIT_EVENTS = frozenset(
    {
        QEvent.Type.FontChange,
        QEvent.Type.StyleChange,
        QEvent.Type.ApplicationFontChange,
        QEvent.Type.DevicePixelRatioChange,
        QEvent.Type.LanguageChange,
        QEvent.Type.ScreenChangeInternal,
    }
)


def should_refit_numeric(event: QEvent) -> bool:
    """True when ``event`` may change spin-box size hints (theme/font/DPI)."""
    return event.type() in _REFIT_EVENTS


def fit_numeric_spinbox(box: QAbstractSpinBox) -> None:
    """Pin ``box`` to the style size hint for its range, digits, suffix, and special text.

    ``QFormLayout`` grows every non-fixed field to the page width. A spin box
    only needs room for the widest value it can show. Call again after
    ``setRange`` / ``setSuffix`` / theme or font changes (pages typically do
    this from ``changeEvent`` via :func:`fit_numeric_spinboxes`).
    """
    box.ensurePolished()
    width = max(box.sizeHint().width(), box.minimumSizeHint().width(), 1)
    box.setFixedWidth(width)
    policy = box.sizePolicy()
    policy.setHorizontalPolicy(QSizePolicy.Policy.Fixed)
    policy.setVerticalPolicy(QSizePolicy.Policy.Fixed)
    box.setSizePolicy(policy)


def fit_numeric_spinboxes(root: QWidget) -> None:
    """Apply :func:`fit_numeric_spinbox` to every spin box under ``root``."""
    for box in root.findChildren(QAbstractSpinBox):
        fit_numeric_spinbox(box)
