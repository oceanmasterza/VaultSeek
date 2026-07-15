"""SQLite engine factory with MusicVault's required PRAGMA configuration.

See docs/architecture/12-pipeline-engine-v3.md ("PRAGMA Configuration
(Revised)") for the rationale behind each setting — in particular the
adaptive ``mmap_size`` cap. A fixed 30 GB cap (as an earlier external
review suggested) can cause the OS to overcommit virtual address space
and degrade performance on memory-constrained systems, since
``mmap_size`` is an upper bound on memory-mapped I/O, not a memory
allocation. Scaling it to a fraction of *available* RAM is safer.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import psutil
from sqlalchemy import Engine, create_engine, event

_MMAP_CEILING_BYTES = 30 * 1024**3  # 30 GB — matches the reviewed recommendation's cap
_MMAP_FLOOR_BYTES = 256 * 1024**2  # 256 MB — never mmap less than this
_MMAP_RAM_FRACTION = 0.25
_BUSY_TIMEOUT_MS = 5000
_CACHE_SIZE_KIB = -64000  # negative value = KiB of page cache, not a page count

_STATIC_PRAGMAS = (
    "PRAGMA journal_mode = WAL",
    "PRAGMA synchronous = NORMAL",
    f"PRAGMA cache_size = {_CACHE_SIZE_KIB}",
    "PRAGMA temp_store = MEMORY",
    "PRAGMA foreign_keys = ON",
    f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}",
)


def adaptive_mmap_size_bytes() -> int:
    """Compute the `mmap_size` PRAGMA value: 25% of available RAM,
    floored at 256 MB and capped at 30 GB."""
    available_ram = psutil.virtual_memory().available
    cap = min(_MMAP_CEILING_BYTES, int(available_ram * _MMAP_RAM_FRACTION))
    return max(cap, _MMAP_FLOOR_BYTES)


def _configure_sqlite_connection(dbapi_connection: sqlite3.Connection, _record: Any) -> None:
    """Apply MusicVault's required PRAGMAs to a newly opened connection.

    Registered against SQLAlchemy's pool-level ``connect`` event (rather
    than run once at engine creation) because SQLite PRAGMAs are
    per-connection state: every new physical connection the pool opens
    starts from SQLite's defaults and must be reconfigured.
    """
    cursor = dbapi_connection.cursor()
    try:
        for pragma in _STATIC_PRAGMAS:
            cursor.execute(pragma)
        cursor.execute(f"PRAGMA mmap_size = {adaptive_mmap_size_bytes()}")
    finally:
        cursor.close()


def create_sqlite_engine(db_path: Path, *, echo: bool = False) -> Engine:
    """Create a SQLAlchemy engine for the MusicVault database at ``db_path``.

    Every connection the returned engine opens has WAL mode, foreign key
    enforcement, and the rest of MusicVault's PRAGMA configuration
    applied automatically.
    """
    engine = create_engine(f"sqlite:///{db_path}", echo=echo)
    event.listen(engine, "connect", _configure_sqlite_connection)
    return engine
