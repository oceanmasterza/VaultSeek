"""Unit tests for musicvault.db.engine."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from sqlalchemy import Engine, text

from musicvault.db.engine import (
    _MMAP_CEILING_BYTES,
    _MMAP_FLOOR_BYTES,
    adaptive_mmap_size_bytes,
    create_sqlite_engine,
)


def _pragma_value(engine: Engine, pragma: str) -> Any:
    with engine.connect() as conn:
        return conn.execute(text(f"PRAGMA {pragma}")).scalar()


def test_create_sqlite_engine_applies_journal_mode_wal(tmp_path: Path) -> None:
    engine = create_sqlite_engine(tmp_path / "test.db")

    assert _pragma_value(engine, "journal_mode") == "wal"
    engine.dispose()


def test_create_sqlite_engine_applies_synchronous_normal(tmp_path: Path) -> None:
    engine = create_sqlite_engine(tmp_path / "test.db")

    # SQLite reports synchronous as an integer: 0=OFF, 1=NORMAL, 2=FULL.
    assert _pragma_value(engine, "synchronous") == 1
    engine.dispose()


def test_create_sqlite_engine_applies_foreign_keys_on(tmp_path: Path) -> None:
    engine = create_sqlite_engine(tmp_path / "test.db")

    assert _pragma_value(engine, "foreign_keys") == 1
    engine.dispose()


def test_create_sqlite_engine_applies_temp_store_memory(tmp_path: Path) -> None:
    engine = create_sqlite_engine(tmp_path / "test.db")

    # SQLite reports temp_store as an integer: 0=DEFAULT, 1=FILE, 2=MEMORY.
    assert _pragma_value(engine, "temp_store") == 2
    engine.dispose()


def test_create_sqlite_engine_applies_busy_timeout(tmp_path: Path) -> None:
    engine = create_sqlite_engine(tmp_path / "test.db")

    assert _pragma_value(engine, "busy_timeout") == 5000
    engine.dispose()


def test_create_sqlite_engine_applies_cache_size(tmp_path: Path) -> None:
    engine = create_sqlite_engine(tmp_path / "test.db")

    assert _pragma_value(engine, "cache_size") == -64000
    engine.dispose()


def test_create_sqlite_engine_applies_positive_mmap_size(tmp_path: Path) -> None:
    engine = create_sqlite_engine(tmp_path / "test.db")

    assert int(_pragma_value(engine, "mmap_size")) > 0
    engine.dispose()


def test_pragmas_reapplied_on_every_new_pooled_connection(tmp_path: Path) -> None:
    """Each connection the pool opens must independently get the pragmas —
    not just the first one — since SQLite pragmas are per-connection."""
    engine = create_sqlite_engine(tmp_path / "test.db")

    with engine.connect() as first:
        assert first.execute(text("PRAGMA foreign_keys")).scalar() == 1

    with engine.connect() as second:
        assert second.execute(text("PRAGMA foreign_keys")).scalar() == 1

    engine.dispose()


def test_create_sqlite_engine_creates_the_database_file(tmp_path: Path) -> None:
    db_path = tmp_path / "subdir_not_created" / "test.db"
    db_path.parent.mkdir()

    engine = create_sqlite_engine(db_path)
    with engine.connect():
        pass

    assert db_path.exists()
    engine.dispose()


def test_adaptive_mmap_size_never_below_floor() -> None:
    with patch("musicvault.db.engine.psutil.virtual_memory") as mock_vm:
        mock_vm.return_value = MagicMock(available=1)  # pathologically low RAM
        assert adaptive_mmap_size_bytes() == _MMAP_FLOOR_BYTES


def test_adaptive_mmap_size_never_above_ceiling() -> None:
    with patch("musicvault.db.engine.psutil.virtual_memory") as mock_vm:
        mock_vm.return_value = MagicMock(available=1024**4)  # 1 TB, implausibly high
        assert adaptive_mmap_size_bytes() == _MMAP_CEILING_BYTES


def test_adaptive_mmap_size_scales_to_quarter_of_available_ram() -> None:
    available = 16 * 1024**3  # 16 GB — well within floor/ceiling bounds
    with patch("musicvault.db.engine.psutil.virtual_memory") as mock_vm:
        mock_vm.return_value = MagicMock(available=available)
        assert adaptive_mmap_size_bytes() == available // 4
