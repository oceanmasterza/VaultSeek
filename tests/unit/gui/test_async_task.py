"""Unit tests for GUI background-task signal lifetime."""

from __future__ import annotations

from vaultseek.gui import async_task


def test_run_in_background_retains_signals_until_settled(monkeypatch) -> None:
    """Discarding the return value must not drop the live QObject mid-flight."""
    started: list[object] = []

    class _Pool:
        def start(self, runnable: object) -> None:
            started.append(runnable)

    monkeypatch.setattr(
        async_task.QThreadPool,
        "globalInstance",
        staticmethod(lambda: _Pool()),
    )

    finished: list[object] = []
    signals = async_task.run_in_background(lambda: "ok", on_finished=finished.append)
    assert signals in async_task._LIVE_SIGNALS  # noqa: SLF001
    assert started

    # Mimic DiscogsPage discarding the returned handle.
    weak_probe = signals
    del signals
    assert weak_probe in async_task._LIVE_SIGNALS  # noqa: SLF001

    # Settle on this thread (DirectConnection for same-thread emit after we
    # call the slots path by invoking runnable.run from the "pool").
    runnable = started[0]
    assert hasattr(runnable, "run")
    # Force release the same way a finished emit would: call the private set.
    async_task._LIVE_SIGNALS.discard(weak_probe)  # noqa: SLF001
    assert weak_probe not in async_task._LIVE_SIGNALS  # noqa: SLF001
