"""MediaServerStateRepository — persistence for media_server_state."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Engine, Row, select, update

from vaultseek.db.repositories.base import batch_upsert
from vaultseek.db.tables import media_server_state as media_server_state_table
from vaultseek.db.uuid_utils import blob_to_uuid, uuid_to_blob
from vaultseek.models.entities.media_server_state import MediaServerState


class MediaServerStateRepository:
    """Reads and writes media-server connection rows."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def upsert(self, state: MediaServerState) -> None:
        with self._engine.begin() as conn:
            batch_upsert(
                conn,
                media_server_state_table,
                [_to_row(state)],
                conflict_columns=["id"],
            )

    def get(self, state_id: UUID) -> MediaServerState | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                select(media_server_state_table).where(
                    media_server_state_table.c.id == uuid_to_blob(state_id)
                )
            ).first()
        return _from_row(row) if row is not None else None

    def list_by_library(self, library_id: UUID) -> list[MediaServerState]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                select(media_server_state_table).where(
                    media_server_state_table.c.library_id == uuid_to_blob(library_id)
                )
            ).all()
        return [_from_row(row) for row in rows]

    def update_sync_status(
        self,
        state_id: UUID,
        *,
        status: str,
        synced_at: datetime,
    ) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                update(media_server_state_table)
                .where(media_server_state_table.c.id == uuid_to_blob(state_id))
                .values(
                    last_sync_status=status,
                    last_sync_at=synced_at.isoformat(),
                )
            )


def _to_row(state: MediaServerState) -> dict[str, object]:
    config_json = json.dumps(state.config) if state.config is not None else None
    return {
        "id": uuid_to_blob(state.id),
        "library_id": uuid_to_blob(state.library_id),
        "plugin_id": state.plugin_id,
        "server_url": state.server_url,
        "db_path": state.db_path,
        "config": config_json,
        "last_sync_at": state.last_sync_at.isoformat() if state.last_sync_at else None,
        "last_sync_status": state.last_sync_status,
    }


def _from_row(row: Row[Any]) -> MediaServerState:
    config: dict[str, Any] | None = None
    if row.config:
        parsed = json.loads(row.config)
        if isinstance(parsed, dict):
            config = parsed
    return MediaServerState(
        id=blob_to_uuid(row.id),
        library_id=blob_to_uuid(row.library_id),
        plugin_id=row.plugin_id,
        server_url=row.server_url,
        db_path=row.db_path,
        config=config,
        last_sync_at=(datetime.fromisoformat(row.last_sync_at) if row.last_sync_at else None),
        last_sync_status=row.last_sync_status,
    )
