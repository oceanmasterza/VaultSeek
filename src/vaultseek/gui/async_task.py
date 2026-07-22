"""Non-blocking helpers to run work off the Qt UI thread."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal


class _TaskSignals(QObject):
    finished = Signal(object)
    failed = Signal(str)


class _Runnable(QRunnable):
    def __init__(self, fn: Callable[[], Any], signals: _TaskSignals) -> None:
        super().__init__()
        self._fn = fn
        self._signals = signals
        self.setAutoDelete(True)

    def run(self) -> None:  # noqa: D401 — Qt entry point
        try:
            self._signals.finished.emit(self._fn())
        except Exception as exc:  # noqa: BLE001 — surface to UI
            self._signals.failed.emit(str(exc))


def run_in_background(
    fn: Callable[[], Any],
    *,
    on_finished: Callable[[Any], None],
    on_failed: Callable[[str], None] | None = None,
) -> _TaskSignals:
    """Run ``fn`` on the global Qt thread pool; callbacks fire on the UI thread."""
    signals = _TaskSignals()
    signals.finished.connect(on_finished)
    if on_failed is not None:
        signals.failed.connect(on_failed)
    QThreadPool.globalInstance().start(_Runnable(fn, signals))
    return signals
