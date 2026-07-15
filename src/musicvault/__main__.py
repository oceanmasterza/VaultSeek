"""Command-line entry point: ``python -m musicvault``.

For now this only verifies that the application can bootstrap
successfully — load configuration, configure logging, migrate and open
the database, and build the dependency container — then exits. The GUI
entry point is introduced in Phase 14 (see
docs/architecture/07-roadmap.md).
"""

from __future__ import annotations

import sys

from loguru import logger

from musicvault import __version__
from musicvault.app import bootstrap
from musicvault.core.exceptions import MusicVaultError


def main() -> int:
    """Bootstrap the application and report readiness.

    Returns:
        Process exit code: ``0`` on success, ``1`` if bootstrap fails.
    """
    print(f"MusicVault {__version__}")
    try:
        container = bootstrap()
    except MusicVaultError as exc:
        print(f"Failed to start MusicVault: {exc}", file=sys.stderr)
        return 1

    try:
        logger.info("MusicVault {} ready (data directory: {})", __version__, container.paths.root)
    finally:
        container.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
