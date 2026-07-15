"""Alembic migration environment for the MusicVault schema.

``env.py`` wires Alembic to :mod:`musicvault.db.tables`. Use
:func:`musicvault.db.migrations.runner.run_migrations` to apply migrations
programmatically from application or test code — the ``alembic`` CLI
(driven by the repo-root ``alembic.ini``) is for manual development use
only (e.g. ``alembic revision --autogenerate``).
"""
