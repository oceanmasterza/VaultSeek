"""Loguru configuration for VaultSeek.

Sinks configured:

* Console — human-readable, colorized, ``level`` and above (optional).
* ``vaultseek.log`` — user-facing operations, INFO and above, rotated.
* ``debug.log`` — full diagnostic detail, DEBUG and above, rotated.
* ``crashes/`` — one file per session with ERROR-and-above events only,
  for post-mortem crash analysis.
* :class:`LiveLogBuffer` — in-memory ring buffer for the Dashboard live panel.

Callers must ensure ``paths.logs_dir`` and ``paths.crashes_dir`` already
exist (see :meth:`vaultseek.core.paths.AppPaths.ensure_created`) before
calling :func:`configure_logging`.
"""

from __future__ import annotations

import sys
import threading
from collections import deque

from loguru import logger

from vaultseek.core.paths import AppPaths

_CONSOLE_FORMAT = (
    "<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>"
)
_FILE_FORMAT = "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}"
_LIVE_FORMAT = "{time:HH:mm:ss} | {level: <7} | {message}"

_ROTATION = "10 MB"
_RETENTION = 5
_LIVE_LOG_CAPACITY = 400

_live_buffer: LiveLogBuffer | None = None


class LiveLogBuffer:
    """Thread-safe ring buffer of recent log lines for the Dashboard."""

    def __init__(self, capacity: int = _LIVE_LOG_CAPACITY) -> None:
        self._capacity = max(1, capacity)
        self._lines: deque[str] = deque(maxlen=self._capacity)
        self._lock = threading.Lock()
        self._generation = 0

    def write(self, message: str) -> None:
        text = message.rstrip("\n")
        if not text:
            return
        with self._lock:
            self._lines.append(text)
            self._generation += 1

    def lines(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._lines)

    def text(self) -> str:
        return "\n".join(self.lines())

    def snapshot(self) -> tuple[int, tuple[str, ...]]:
        """Return ``(generation, lines)`` for cheap UI change detection."""
        with self._lock:
            return self._generation, tuple(self._lines)

    def clear(self) -> None:
        with self._lock:
            self._lines.clear()
            self._generation += 1

    def __len__(self) -> int:
        with self._lock:
            return len(self._lines)


def get_live_log_buffer() -> LiveLogBuffer:
    """Return the process-wide live log buffer (created on first configure)."""
    global _live_buffer
    if _live_buffer is None:
        _live_buffer = LiveLogBuffer()
    return _live_buffer


def configure_logging(paths: AppPaths, *, level: str = "INFO", console: bool = True) -> None:
    """Reset and (re)configure all Loguru sinks.

    Safe to call multiple times (e.g. after a config reload) — existing
    sinks are removed before new ones are added, so repeated calls never
    duplicate log lines.
    """
    global _live_buffer
    logger.remove()

    if _live_buffer is None:
        _live_buffer = LiveLogBuffer()

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
    logger.add(
        _live_buffer.write,
        level="INFO",
        format=_LIVE_FORMAT,
        colorize=False,
    )
