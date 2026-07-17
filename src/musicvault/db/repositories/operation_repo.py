"""OperationRepository — persistence for `operations` and `change_history`.

Phase 10 writes one operation + change row per file move so the Phase 12
rollback engine has an audit trail to roll back from. Snapshot storage
(`rollback_snapshots`) stays Phase 12.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Engine, Row, insert, select

from musicvault.db.tables import change_history, operations
from musicvault.db.uuid_utils import blob_to_uuid, uuid_to_blob
from musicvault.models.entities.operation import (
    ChangeRecord,
    ChangeType,
    Operation,
    OperationStatus,
    OperationType,
)


class OperationRepository:
    """Reads and writes `Operation` / `ChangeRecord` audit rows."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def record(self, operation: Operation, changes: list[ChangeRecord]) -> None:
        """Insert an operation together with its change rows atomically."""
        with self._engine.begin() as conn:
            conn.execute(insert(operations).values(**_operation_to_row(operation)))
            if changes:
                conn.execute(
                    insert(change_history),
                    [_change_to_row(change) for change in changes],
                )

    def get(self, operation_id: UUID) -> Operation | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                select(operations).where(operations.c.id == uuid_to_blob(operation_id))
            ).first()
        return _operation_from_row(row) if row is not None else None

    def list_changes(self, operation_id: UUID) -> list[ChangeRecord]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                select(change_history).where(
                    change_history.c.operation_id == uuid_to_blob(operation_id)
                )
            ).all()
        return [_change_from_row(row) for row in rows]

    def list_changes_for_track(self, track_id: UUID) -> list[ChangeRecord]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                select(change_history)
                .where(change_history.c.track_id == uuid_to_blob(track_id))
                .order_by(change_history.c.timestamp)
            ).all()
        return [_change_from_row(row) for row in rows]


def _operation_to_row(operation: Operation) -> dict[str, object]:
    return {
        "id": uuid_to_blob(operation.id),
        "operation_type": operation.operation_type.value,
        "status": operation.status.value,
        "is_dry_run": operation.is_dry_run,
        "description": operation.description,
        "affected_count": operation.affected_count,
        "started_at": operation.started_at.isoformat(),
        "completed_at": (operation.completed_at.isoformat() if operation.completed_at else None),
        "snapshot_id": uuid_to_blob(operation.snapshot_id) if operation.snapshot_id else None,
    }


def _operation_from_row(row: Row[Any]) -> Operation:
    return Operation(
        id=blob_to_uuid(row.id),
        operation_type=OperationType(row.operation_type),
        status=OperationStatus(row.status),
        is_dry_run=bool(row.is_dry_run),
        description=row.description,
        affected_count=row.affected_count,
        started_at=datetime.fromisoformat(row.started_at),
        completed_at=(datetime.fromisoformat(row.completed_at) if row.completed_at else None),
        snapshot_id=blob_to_uuid(row.snapshot_id) if row.snapshot_id else None,
    )


def _change_to_row(change: ChangeRecord) -> dict[str, object]:
    return {
        "id": uuid_to_blob(change.id),
        "operation_id": uuid_to_blob(change.operation_id),
        "track_id": uuid_to_blob(change.track_id) if change.track_id else None,
        "change_type": change.change_type.value,
        "field_name": change.field_name,
        "old_value": change.old_value,
        "new_value": change.new_value,
        "old_file_path": change.old_file_path,
        "new_file_path": change.new_file_path,
        "old_zone": change.old_zone,
        "new_zone": change.new_zone,
        "timestamp": change.timestamp.isoformat(),
    }


def _change_from_row(row: Row[Any]) -> ChangeRecord:
    return ChangeRecord(
        id=blob_to_uuid(row.id),
        operation_id=blob_to_uuid(row.operation_id),
        track_id=blob_to_uuid(row.track_id) if row.track_id else None,
        change_type=ChangeType(row.change_type),
        field_name=row.field_name,
        old_value=row.old_value,
        new_value=row.new_value,
        old_file_path=row.old_file_path,
        new_file_path=row.new_file_path,
        old_zone=row.old_zone,
        new_zone=row.new_zone,
        timestamp=datetime.fromisoformat(row.timestamp),
    )
