"""Integration tests for the Alembic migration environment.

Exercises the real `alembic` machinery (not a mock) against a real
temp-file SQLite database, because the whole point of Phase 2's
acceptance criteria is that upgrade/downgrade actually work end to end.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from musicvault.core.exceptions import DatabaseError
from musicvault.db.migrations.runner import downgrade_migrations, run_migrations

EXPECTED_TABLE_NAMES = {
    "libraries",
    "artists",
    "albums",
    "tracks",
    "file_identity",
    "metadata_confidence",
    "jobs",
    "review_items",
    "rules",
    "duplicate_groups",
    "duplicate_members",
    "operations",
    "change_history",
    "rollback_snapshots",
    "media_server_state",
    "artwork",
    "track_artwork",
    "album_artwork",
}


def _sqlite_table_names(db_path: Path) -> set[str]:
    engine = create_engine(f"sqlite:///{db_path}")
    try:
        with engine.connect() as conn:
            rows = conn.execute(text("SELECT name FROM sqlite_master WHERE type = 'table'")).all()
    finally:
        engine.dispose()
    return {row.name for row in rows}


def test_run_migrations_creates_the_database_file(tmp_path: Path) -> None:
    db_path = tmp_path / "does_not_exist_yet" / "musicvault.db"
    db_path.parent.mkdir()

    run_migrations(db_path)

    assert db_path.exists()


def test_run_migrations_creates_all_specified_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "musicvault.db"

    run_migrations(db_path)

    tables = _sqlite_table_names(db_path)
    assert EXPECTED_TABLE_NAMES.issubset(tables)


def test_run_migrations_records_alembic_version(tmp_path: Path) -> None:
    db_path = tmp_path / "musicvault.db"

    run_migrations(db_path)

    engine = create_engine(f"sqlite:///{db_path}")
    try:
        with engine.connect() as conn:
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
    finally:
        engine.dispose()

    assert version == "0003"


def test_downgrade_to_base_drops_all_specified_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "musicvault.db"
    run_migrations(db_path)

    downgrade_migrations(db_path, "base")

    tables = _sqlite_table_names(db_path)
    assert EXPECTED_TABLE_NAMES.isdisjoint(tables)


def test_upgrade_downgrade_upgrade_round_trip_is_repeatable(tmp_path: Path) -> None:
    """Proves the migration is safe to run more than once — e.g. after a
    user rolls back and then re-applies an update."""
    db_path = tmp_path / "musicvault.db"

    run_migrations(db_path)
    assert EXPECTED_TABLE_NAMES.issubset(_sqlite_table_names(db_path))

    downgrade_migrations(db_path, "base")
    assert EXPECTED_TABLE_NAMES.isdisjoint(_sqlite_table_names(db_path))

    run_migrations(db_path)
    assert EXPECTED_TABLE_NAMES.issubset(_sqlite_table_names(db_path))


def test_run_migrations_is_a_no_op_when_already_up_to_date(tmp_path: Path) -> None:
    db_path = tmp_path / "musicvault.db"

    run_migrations(db_path)
    run_migrations(db_path)  # must not raise

    assert EXPECTED_TABLE_NAMES.issubset(_sqlite_table_names(db_path))


def test_run_migrations_wraps_failures_in_database_error(tmp_path: Path) -> None:
    """A SQLite open failure (here: the parent directory does not exist)
    should surface as a `DatabaseError`, not a raw Alembic/SQLAlchemy
    exception — see `run_migrations`'s docstring."""
    db_path = tmp_path / "missing_directory" / "musicvault.db"

    with pytest.raises(DatabaseError) as exc_info:
        run_migrations(db_path)
    assert str(db_path) in str(exc_info.value)


def test_downgrade_migrations_wraps_failures_in_database_error(tmp_path: Path) -> None:
    """An unknown target revision should surface as a `DatabaseError`,
    mirroring `run_migrations`'s error translation."""
    db_path = tmp_path / "musicvault.db"
    run_migrations(db_path)

    with pytest.raises(DatabaseError) as exc_info:
        downgrade_migrations(db_path, "not_a_real_revision")
    assert str(db_path) in str(exc_info.value)
