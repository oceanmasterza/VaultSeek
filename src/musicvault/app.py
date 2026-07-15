"""Application bootstrap sequence.

Wires together paths, configuration, logging, the database (migrated
and opened by :meth:`Container.bootstrap`), and the dependency
injection container. This module contains no GUI code — see
docs/architecture/01-overview.md for the full startup flow once the
job queue and GUI layers exist (Phases 4–14).
"""

from __future__ import annotations

from pathlib import Path

from loguru import logger

from musicvault import __version__
from musicvault.core.config import load_config
from musicvault.core.container import Container
from musicvault.core.logging import configure_logging
from musicvault.core.paths import AppPaths, get_app_paths


def bootstrap(*, base_dir_override: Path | None = None, console_logging: bool = True) -> Container:
    """Run the full startup sequence and return a wired :class:`Container`.

    Args:
        base_dir_override: Overrides the platform application data
            directory. Tests pass a temporary directory here to stay
            isolated from the real user profile.
        console_logging: Whether to emit logs to stderr in addition to the
            rotating log files. Test fixtures disable this to keep output
            quiet.
    """
    paths: AppPaths = get_app_paths(base_override=base_dir_override)
    paths.ensure_created()

    config = load_config(paths.config_file)
    configure_logging(paths, level=config.log_level, console=console_logging)

    logger.info("MusicVault {} starting up", __version__)
    logger.debug("Application data directory: {}", paths.root)

    return Container.bootstrap(paths=paths, config=config)
