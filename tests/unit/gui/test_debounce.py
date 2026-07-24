"""Tests for search-box debounce helper."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QWidget

from vaultseek.gui.debounce import connect_debounced


class _Emitter(QObject):
    changed = Signal(str)


def test_connect_debounced_collapses_bursts(qtbot) -> None:
    parent = QWidget()
    qtbot.addWidget(parent)
    emitter = _Emitter(parent)
    calls: list[int] = []

    connect_debounced(
        emitter.changed,
        lambda: calls.append(1),
        parent=parent,
        delay_ms=40,
    )

    emitter.changed.emit("a")
    emitter.changed.emit("ab")
    emitter.changed.emit("abc")
    assert calls == []

    qtbot.wait(80)
    assert calls == [1]
