"""Command-line entry point: ``python -m musicvault``.

Bootstraps the application, then either launches the Qt GUI (default) or
exits after a headless readiness check when ``--headless`` is passed or
``MUSICVAULT_HEADLESS=1`` is set (CI / automation).
"""

from __future__ import annotations

import os
import sys

from loguru import logger

from musicvault import __version__
from musicvault.app import bootstrap
from musicvault.core.exceptions import MusicVaultError


def _wants_headless(argv: list[str]) -> bool:
    if "--headless" in argv:
        return True
    flag = os.environ.get("MUSICVAULT_HEADLESS", "").strip().lower()
    return flag in {"1", "true", "yes"}


def main(argv: list[str] | None = None) -> int:
    """Bootstrap MusicVault and launch the GUI (or headless check).

    Returns:
        Process exit code: ``0`` on success, ``1`` if bootstrap fails.
    """
    args = list(sys.argv[1:] if argv is None else argv)
    print(f"MusicVault {__version__}")
    try:
        container = bootstrap()
    except MusicVaultError as exc:
        print(f"Failed to start MusicVault: {exc}", file=sys.stderr)
        return 1

    if _wants_headless(args):
        try:
            logger.info(
                "MusicVault {} ready (headless; data directory: {})",
                __version__,
                container.paths.root,
            )
        finally:
            container.close()
        return 0

    from musicvault.gui.app import run_gui

    return run_gui(container)


if __name__ == "__main__":
    sys.exit(main())
