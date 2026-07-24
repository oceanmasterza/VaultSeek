"""Debounce Qt signal handlers so typing / rapid updates don't flood the UI."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer


def connect_debounced(
    signal: object,
    slot: Callable[[], None],
    *,
    parent: QObject,
    delay_ms: int = 250,
) -> QTimer:
    """Connect ``signal`` so ``slot`` runs only after ``delay_ms`` of quiet.

    Restarting the timer on each emission collapses bursts (e.g. search box
    ``textChanged``) into a single refresh after the user pauses typing.
    """
    timer = QTimer(parent)
    timer.setSingleShot(True)
    timer.setInterval(max(0, int(delay_ms)))
    timer.timeout.connect(slot)

    def _restart(*_args: object) -> None:
        timer.start()

    signal.connect(_restart)  # type: ignore[attr-defined]
    return timer
