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

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.util.exc import CommandError
from sqlalchemy.exc import SQLAlchemyError

from musicvault.core.exceptions import DatabaseError

_MIGRATIONS_DIR = Path(__file__).parent


def run_migrations(db_path: Path, *, revision: str = "head") -> None:
    """Upgrade the SQLite database at ``db_path`` to ``revision`` (default: latest).

    Creates the database file if it does not already exist — this is how
    MusicVault satisfies "DB auto-created on first run": application
    startup calls this before doing anything else.

    Raises:
        DatabaseError: if Alembic or the underlying SQLite connection
            fails (e.g. a locked file, missing directory, or corrupt
            database) — translated so callers only need to catch
            :class:`~musicvault.core.exceptions.MusicVaultError`.
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
    config.set_main_option("script_location", str(_MIGRATIONS_DIR))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    return config
