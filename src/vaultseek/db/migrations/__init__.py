"""Alembic migration environment for the VaultSeek schema.

``env.py`` wires Alembic to :mod:`vaultseek.db.tables`. Use
:func:`vaultseek.db.migrations.runner.run_migrations` to apply migrations
programmatically from application or test code — the ``alembic`` CLI
(driven by the repo-root ``alembic.ini``) is for manual development use
only (e.g. ``alembic revision --autogenerate``).
"""
