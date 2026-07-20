"""OperationRepository — persistence for operations, change history, snapshots.

Phase 10 wrote operation + change rows per file move. Phase 12 adds
``rollback_snapshots`` (gzip-compressed JSON BLOB) and status updates
so :class:`~vaultseek.services.operation_orchestrator.OperationOrchestrator`
can reverse completed mutations.
"""

from __future__ import annotations

import gzip
import json
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Engine, Row, insert, select, update

from vaultseek.db.tables import change_history, operations, rollback_snapshots
from vaultseek.db.uuid_utils import blob_to_uuid, uuid_to_blob
from vaultseek.models.entities.operation import (
    ChangeRecord,
    ChangeType,
    Operation,
    OperationStatus,
    OperationType,
    RollbackSnapshot,
)

# Snapshot JSON schema version — bump when the document shape changes.
SNAPSHOT_SCHEMA_VERSION = 1


class OperationRepository:
    """Reads and writes `Operation` / `ChangeRecord` / `RollbackSnapshot` rows."""

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

    def record_with_snapshot(
        self,
        operation: Operation,
        changes: list[ChangeRecord],
        snapshot: RollbackSnapshot,
    ) -> None:
        """Insert operation + changes + snapshot, then backfill ``snapshot_id``.

        The schema has a circular FK (``operations.snapshot_id`` ↔
        ``rollback_snapshots.operation_id``); insert order is operation →
        snapshot → update operation, matching the Phase 2 table tests.
        """
        with self._engine.begin() as conn:
            # Insert without snapshot_id first — the FK target does not exist yet.
            row = _operation_to_row(operation)
            row["snapshot_id"] = None
            conn.execute(insert(operations).values(**row))
            if changes:
                conn.execute(
                    insert(change_history),
                    [_change_to_row(change) for change in changes],
                )
            conn.execute(insert(rollback_snapshots).values(**_snapshot_to_row(snapshot)))
            conn.execute(
                update(operations)
                .where(operations.c.id == uuid_to_blob(operation.id))
                .values(snapshot_id=uuid_to_blob(snapshot.id))
            )

    def get(self, operation_id: UUID) -> Operation | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                select(operations).where(operations.c.id == uuid_to_blob(operation_id))
            ).first()
        return _operation_from_row(row) if row is not None else None

    def list_recent(self, *, limit: int = 50) -> list[Operation]:
        """Newest operations first (zone-aware history browse)."""
        statement = select(operations).order_by(operations.c.started_at.desc()).limit(limit)
        with self._engine.connect() as conn:
            rows = conn.execute(statement).all()
        return [_operation_from_row(row) for row in rows]

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

    def get_snapshot(self, snapshot_id: UUID) -> RollbackSnapshot | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                select(rollback_snapshots).where(
                    rollback_snapshots.c.id == uuid_to_blob(snapshot_id)
                )
            ).first()
        return _snapshot_from_row(row) if row is not None else None

    def get_snapshot_for_operation(self, operation_id: UUID) -> RollbackSnapshot | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                select(rollback_snapshots).where(
                    rollback_snapshots.c.operation_id == uuid_to_blob(operation_id)
                )
            ).first()
        return _snapshot_from_row(row) if row is not None else None

    def set_status(
        self,
        operation_id: UUID,
        status: OperationStatus,
        *,
        completed_at: datetime | None = None,
    ) -> None:
        values: dict[str, object] = {"status": status.value}
        if completed_at is not None:
            values["completed_at"] = completed_at.isoformat()
        with self._engine.begin() as conn:
            conn.execute(
                update(operations)
                .where(operations.c.id == uuid_to_blob(operation_id))
                .values(**values)
            )

    def mark_snapshot_restored(self, snapshot_id: UUID, restored_at: datetime) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                update(rollback_snapshots)
                .where(rollback_snapshots.c.id == uuid_to_blob(snapshot_id))
                .values(restored_at=restored_at.isoformat())
            )


def build_move_snapshot_payload(changes: list[ChangeRecord]) -> dict[str, Any]:
    """JSON document stored (gzip-compressed) in ``snapshot_data``."""
    return {
        "version": SNAPSHOT_SCHEMA_VERSION,
        "changes": [
            {
                "track_id": str(change.track_id) if change.track_id else None,
                "change_type": change.change_type.value,
                "old_file_path": change.old_file_path,
                "new_file_path": change.new_file_path,
                "old_zone": change.old_zone,
                "new_zone": change.new_zone,
            }
            for change in changes
        ],
    }


def encode_snapshot_data(payload: dict[str, Any]) -> bytes:
    """Gzip-compress a JSON snapshot document for BLOB storage."""
    return gzip.compress(json.dumps(payload, separators=(",", ":")).encode("utf-8"))


def decode_snapshot_data(blob: bytes) -> dict[str, Any]:
    """Decompress and parse a ``snapshot_data`` BLOB."""
    payload = json.loads(gzip.decompress(blob).decode("utf-8"))
    if not isinstance(payload, dict):
        raise TypeError("snapshot_data must decode to a JSON object")
    return payload


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


def _snapshot_to_row(snapshot: RollbackSnapshot) -> dict[str, object]:
    # ``snapshot.snapshot_data`` is already gzip-compressed bytes.
    return {
        "id": uuid_to_blob(snapshot.id),
        "operation_id": uuid_to_blob(snapshot.operation_id),
        "snapshot_data": snapshot.snapshot_data,
        "created_at": snapshot.created_at.isoformat(),
        "restored_at": (snapshot.restored_at.isoformat() if snapshot.restored_at else None),
    }


def _snapshot_from_row(row: Row[Any]) -> RollbackSnapshot:
    return RollbackSnapshot(
        id=blob_to_uuid(row.id),
        operation_id=blob_to_uuid(row.operation_id),
        snapshot_data=bytes(row.snapshot_data),
        created_at=datetime.fromisoformat(row.created_at),
        restored_at=(datetime.fromisoformat(row.restored_at) if row.restored_at else None),
    )
