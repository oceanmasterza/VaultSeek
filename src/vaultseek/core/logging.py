"""Loguru configuration for VaultSeek.

Four sinks are configured:

* Console — human-readable, colorized, ``level`` and above (optional).
* ``vaultseek.log`` — user-facing operations, INFO and above, rotated.
* ``debug.log`` — full diagnostic detail, DEBUG and above, rotated.
* ``crashes/`` — one file per session with ERROR-and-above events only,
  for post-mortem crash analysis.

Callers must ensure ``paths.logs_dir`` and ``paths.crashes_dir`` already
exist (see :meth:`vaultseek.core.paths.AppPaths.ensure_created`) before
calling :func:`configure_logging`.
"""

from __future__ import annotations

import sys

from loguru import logger

from vaultseek.core.paths import AppPaths

_CONSOLE_FORMAT = (
    "<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>"
)
_FILE_FORMAT = "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}"

_ROTATION = "10 MB"
_RETENTION = 5


def configure_logging(paths: AppPaths, *, level: str = "INFO", console: bool = True) -> None:
    """Reset and (re)configure all Loguru sinks.

    Safe to call multiple times (e.g. after a config reload) — existing
    sinks are removed before new ones are added, so repeated calls never
    duplicate log lines.
    """
    logger.remove()

    # PyInstaller --windowed (runw) leaves sys.stderr as None; loguru rejects that.
    if console and sys.stderr is not None:
        logger.add(sys.stderr, level=level, format=_CONSOLE_FORMAT, colorize=True)

    logger.add(
        paths.logs_dir / "vaultseek.log",
        level="INFO",
        format=_FILE_FORMAT,
        rotation=_ROTATION,
        retention=_RETENTION,
        encoding="utf-8",
    )
    logger.add(
        paths.logs_dir / "debug.log",
        level="DEBUG",
        format=_FILE_FORMAT,
        rotation=_ROTATION,
        retention=_RETENTION,
        encoding="utf-8",
    )
    logger.add(
        paths.crashes_dir / "crash_{time:YYYY-MM-DD_HH-mm-ss}.log",
        level="ERROR",
        format=_FILE_FORMAT,
        encoding="utf-8",
    )
