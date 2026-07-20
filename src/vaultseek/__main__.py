"""Command-line entry point: ``python -m vaultseek``.

Bootstraps the application, then either launches the Qt GUI (default) or
exits after a headless readiness check when ``--headless`` is passed or
``VAULTSEEK_HEADLESS=1`` is set (CI / automation).

Frozen Windows builds **must** call ``multiprocessing.freeze_support()``
before any other work: ``ProcessPoolExecutor`` workers re-launch this
executable, and without ``freeze_support`` they re-enter :func:`main`,
fight over SQLite, and can spam hundreds of error dialogs.
"""

from __future__ import annotations

import multiprocessing
import os
import sys
import traceback

from vaultseek import __version__
from vaultseek.core.single_instance import SingleInstanceLock, is_main_process


def _wants_headless(argv: list[str]) -> bool:
    if "--headless" in argv:
        return True
    flag = os.environ.get("VAULTSEEK_HEADLESS", "").strip().lower()
    return flag in {"1", "true", "yes"}


def _report_startup_failure(message: str) -> None:
    """Show a failure once, only from the real main process."""
    if not is_main_process():
        return
    if sys.stderr is not None:
        print(message, file=sys.stderr)
    # Never MessageBox from workers / secondary instances — that caused the
    # desktop-freezing dialog storm when SQLite locked under process spam.
    if getattr(sys, "frozen", False) and os.environ.get("VAULTSEEK_HEADLESS", "").strip() == "":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, message[:2000], "VaultSeek", 0x10)
        except Exception:
            pass


def main(argv: list[str] | None = None) -> int:
    """Bootstrap VaultSeek and launch the GUI (or headless check).

    Returns:
        Process exit code: ``0`` on success, ``1`` if bootstrap fails.
    """
    # Defensive: never bootstrap from a multiprocessing worker.
    if not is_main_process():
        return 0

    from loguru import logger

    from vaultseek.app import bootstrap
    from vaultseek.core.exceptions import VaultSeekError

    args = list(sys.argv[1:] if argv is None else argv)
    if sys.stdout is not None:
        print(f"VaultSeek {__version__}")

    with SingleInstanceLock() as lock:
        if not lock.acquired:
            msg = (
                "VaultSeek is already running.\n\n"
                "Only one instance can use the library database at a time."
            )
            if sys.stderr is not None:
                print(msg, file=sys.stderr)
            # Quiet exit for secondary launches — no MessageBox storm.
            return 0

        try:
            container = bootstrap()
        except VaultSeekError as exc:
            _report_startup_failure(f"Failed to start VaultSeek:\n{exc}")
            return 1
        except Exception as exc:
            _report_startup_failure(
                f"Failed to start VaultSeek:\n{exc}\n\n{traceback.format_exc()}"
            )
            return 1

        if _wants_headless(args):
            try:
                logger.info(
                    "VaultSeek {} ready (headless; data directory: {})",
                    __version__,
                    container.paths.root,
                )
            finally:
                container.close()
            return 0

        from vaultseek.gui.app import run_gui

        return run_gui(container)


if __name__ == "__main__":
    # REQUIRED for PyInstaller + ProcessPoolExecutor on Windows.
    multiprocessing.freeze_support()
    sys.exit(main())
