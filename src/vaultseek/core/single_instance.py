"""Ensure only one VaultSeek GUI/headless process owns the app database.

Without this, a second launch (or a multiprocessing child that mistakenly
re-enters :mod:`vaultseek.__main__`) opens the same SQLite file, hits
``database is locked``, and — if each failure shows a MessageBox — can
freeze the desktop under hundreds of dialogs.
"""

from __future__ import annotations

import sys
from types import TracebackType


class SingleInstanceLock:
    """Cross-process lock. On Windows uses a named mutex; elsewhere a no-op.

    Usage::

        with SingleInstanceLock() as lock:
            if not lock.acquired:
                sys.exit(0)  # another instance is already running
            ...
    """

    def __init__(self, name: str = "Local\\VaultSeekSingleInstance") -> None:
        self._name = name
        self._handle: int | None = None
        self.acquired: bool = False

    def __enter__(self) -> SingleInstanceLock:
        if sys.platform == "win32":
            import ctypes

            kernel32 = ctypes.windll.kernel32
            # CreateMutexW(lpMutexAttributes, bInitialOwner, lpName)
            handle = kernel32.CreateMutexW(None, False, self._name)
            already = kernel32.GetLastError() == 183  # ERROR_ALREADY_EXISTS
            self._handle = handle or None
            self.acquired = bool(handle) and not already
            if already and handle:
                # We did not become the owner — release our reference immediately.
                kernel32.CloseHandle(handle)
                self._handle = None
        else:
            # Non-Windows: allow multiple instances (dev/CI). File locking can
            # be added later if needed.
            self.acquired = True
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._handle is not None and sys.platform == "win32":
            import ctypes

            ctypes.windll.kernel32.CloseHandle(self._handle)
            self._handle = None
        self.acquired = False


def is_main_process() -> bool:
    """False inside ``ProcessPoolExecutor`` / ``multiprocessing`` workers."""
    import multiprocessing

    return multiprocessing.current_process().name == "MainProcess"
