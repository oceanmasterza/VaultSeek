"""LibraryRepository — persistence for the `libraries` table.

First created in Phase 10: the organizer needs zone roots and the
watch-folder service needs `watch_enabled` / `auto_approve_threshold`.
Until a Library Settings GUI exists (Phase 14), rows are created by
tests or future setup flows via :meth:`LibraryRepository.upsert`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Engine, Row, select

from vaultseek.db.repositories.base import batch_upsert
from vaultseek.db.tables import libraries as libraries_table
from vaultseek.db.uuid_utils import blob_to_uuid, uuid_to_blob
from vaultseek.models.entities.library import Library


class LibraryRepository:
    """Reads and writes `Library` entities against the `libraries` table."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def upsert(self, library: Library) -> None:
        with self._engine.begin() as conn:
            batch_upsert(conn, libraries_table, [_to_row(library)], conflict_columns=["id"])

    def get(self, library_id: UUID) -> Library | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                select(libraries_table).where(libraries_table.c.id == uuid_to_blob(library_id))
            ).first()
        return _from_row(row) if row is not None else None

    def list_all(self) -> list[Library]:
        with self._engine.connect() as conn:
            rows = conn.execute(select(libraries_table)).all()
        return [_from_row(row) for row in rows]

    def list_watch_enabled(self) -> list[Library]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                select(libraries_table).where(libraries_table.c.watch_enabled.is_(True))
            ).all()
        return [_from_row(row) for row in rows]


def _to_row(library: Library) -> dict[str, object]:
    return {
        "id": uuid_to_blob(library.id),
        "name": library.name,
        "incoming_path": library.incoming_path,
        "staging_path": library.staging_path,
        "library_path": library.library_path,
        "archive_path": library.archive_path,
        "watch_enabled": library.watch_enabled,
        "auto_approve_threshold": library.auto_approve_threshold,
        "created_at": library.created_at.isoformat(),
        "updated_at": library.updated_at.isoformat(),
    }


def _from_row(row: Row[Any]) -> Library:
    return Library(
        id=blob_to_uuid(row.id),
        name=row.name,
        incoming_path=row.incoming_path,
        staging_path=row.staging_path,
        library_path=row.library_path,
        archive_path=row.archive_path,
        watch_enabled=bool(row.watch_enabled),
        auto_approve_threshold=row.auto_approve_threshold,
        created_at=datetime.fromisoformat(row.created_at),
        updated_at=datetime.fromisoformat(row.updated_at),
    )
