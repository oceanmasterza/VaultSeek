"""Non-blocking helpers to run work off the Qt UI thread."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal


class _TaskSignals(QObject):
    finished = Signal(object)
    failed = Signal(str)


# Keep strong refs until the worker emits finished/failed. Callers often discard
# the returned signals object; without this, Qt/Python can GC the QObject while
# the thread pool is still emitting → native access violation in python312.dll.
_LIVE_SIGNALS: set[_TaskSignals] = set()


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
    """Run ``fn`` on the global Qt thread pool; callbacks fire on the UI thread.

    Retains the signal QObject until the task settles so it cannot be garbage
    collected mid-flight (a common cause of hard Qt/Python crashes when Discogs
    browse or other UI searches run alongside acquisition workers).
    """
    signals = _TaskSignals()
    _LIVE_SIGNALS.add(signals)

    def _release(_arg: object = None) -> None:
        _LIVE_SIGNALS.discard(signals)

    signals.finished.connect(on_finished)
    signals.finished.connect(_release)
    if on_failed is not None:
        signals.failed.connect(on_failed)
    # Always release on failure even when the caller omitted on_failed.
    signals.failed.connect(_release)

    QThreadPool.globalInstance().start(_Runnable(fn, signals))
    return signals
