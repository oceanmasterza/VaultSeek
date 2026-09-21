"""Compact numeric spin boxes keep value-sized widths across range/font changes."""

from __future__ import annotations

from PySide6.QtCore import QEvent
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QSizePolicy, QSpinBox, QWidget

from vaultseek.gui.widgets.numeric_fields import (
    fit_numeric_spinbox,
    fit_numeric_spinboxes,
    should_refit_numeric,
)


def test_fit_numeric_spinbox_uses_fixed_width(qtbot) -> None:  # type: ignore[no-untyped-def]
    box = QSpinBox()
    qtbot.addWidget(box)
    box.setRange(0, 1000)
    fit_numeric_spinbox(box)
    hint = max(box.sizeHint().width(), box.minimumSizeHint().width())
    assert box.width() == hint
    assert box.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Fixed


def test_fit_refits_when_range_grows(qtbot) -> None:  # type: ignore[no-untyped-def]
    box = QSpinBox()
    qtbot.addWidget(box)
    box.setRange(0, 9)
    fit_numeric_spinbox(box)
    narrow = box.width()
    box.setRange(0, 1000000)
    fit_numeric_spinbox(box)
    assert box.width() > narrow
    assert box.width() >= box.sizeHint().width()


def test_fit_refits_when_font_grows(qtbot) -> None:  # type: ignore[no-untyped-def]
    box = QSpinBox()
    qtbot.addWidget(box)
    box.setRange(0, 1000)
    fit_numeric_spinbox(box)
    small = box.width()
    font = QFont(box.font())
    font.setPointSize(max(font.pointSize(), 10) + 8)
    box.setFont(font)
    fit_numeric_spinbox(box)
    assert box.width() >= small
    assert box.width() + 1 >= box.sizeHint().width()


def test_fit_numeric_spinboxes_walks_tree(qtbot) -> None:  # type: ignore[no-untyped-def]
    root = QWidget()
    qtbot.addWidget(root)
    first = QSpinBox(root)
    second = QSpinBox(root)
    first.setRange(1, 20)
    second.setRange(0, 1000)
    fit_numeric_spinboxes(root)
    for box in (first, second):
        hint = max(box.sizeHint().width(), box.minimumSizeHint().width())
        assert box.width() == hint


def test_should_refit_numeric_for_style_and_font() -> None:
    assert should_refit_numeric(QEvent(QEvent.Type.FontChange))
    assert should_refit_numeric(QEvent(QEvent.Type.StyleChange))
    assert not should_refit_numeric(QEvent(QEvent.Type.Show))
