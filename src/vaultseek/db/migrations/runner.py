"""Programmatic Alembic invocation for application and test code.

The ``alembic`` CLI (and the ``sqlalchemy.url`` in the repo-root
``alembic.ini``) is for manual development use only — e.g. running
``alembic revision --autogenerate`` against a scratch database while
designing a new migration. The running application and the test suite
both need to point Alembic at a *different* database on every run (the
real per-user AppData path, or an isolated temp-file path per test), so
they go through this module instead, which builds an in-memory
:class:`~alembic.config.Config` with the URL overridden.
"""

from __future__ import annotations

import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.util.exc import CommandError
from sqlalchemy.exc import SQLAlchemyError

from vaultseek.core.exceptions import DatabaseError


def _migrations_dir() -> Path:
    """Return the on-disk Alembic script tree.

    PyInstaller packs ``.py`` modules into the PYZ archive, so
    ``Path(__file__).parent`` is not a real directory when frozen. The
    packaging spec copies ``vaultseek/db/migrations`` into ``_MEIPASS``.
    """
    packaged = Path(__file__).resolve().parent
    if packaged.is_dir() and (packaged / "env.py").is_file():
        return packaged
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidate = Path(meipass) / "vaultseek" / "db" / "migrations"
        if candidate.is_dir() and (candidate / "env.py").is_file():
            return candidate
    return packaged


def run_migrations(db_path: Path, *, revision: str = "head") -> None:
    """Upgrade the SQLite database at ``db_path`` to ``revision`` (default: latest).

    Creates the database file if it does not already exist — this is how
    VaultSeek satisfies "DB auto-created on first run": application
    startup calls this before doing anything else.

    Raises:
        DatabaseError: if Alembic or the underlying SQLite connection
            fails (e.g. a locked file, missing directory, or corrupt
            database) — translated so callers only need to catch
            :class:`~vaultseek.core.exceptions.VaultSeekError`.
    """
    config = _build_config(db_path)
    try:
        command.upgrade(config, revision)
    except (CommandError, SQLAlchemyError) as exc:
        raise DatabaseError(f"Failed to migrate database at {db_path}: {exc}") from exc


def downgrade_migrations(db_path: Path, revision: str) -> None:
    """Downgrade the SQLite database at ``db_path`` to ``revision``.

    Exists primarily so tests can prove the migration round-trips
    cleanly; the running application never calls this itself.

    Raises:
        DatabaseError: see :func:`run_migrations`.
    """
    config = _build_config(db_path)
    try:
        command.downgrade(config, revision)
    except (CommandError, SQLAlchemyError) as exc:
        raise DatabaseError(f"Failed to downgrade database at {db_path}: {exc}") from exc


def _build_config(db_path: Path) -> Config:
    config = Config()
    config.set_main_option("script_location", str(_migrations_dir()))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    return config
