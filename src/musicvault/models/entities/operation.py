"""Operation / ChangeRecord entities — audit trail for mutating operations.

Mirror the `operations` and `change_history` tables (see
docs/architecture/03-database-schema.md, "Operations & Rollback").
Phase 10 only *writes* these rows (one operation + change per file
move) so the Phase 12 rollback engine has something to roll back;
snapshots (`rollback_snapshots`) and restore stay Phase 12.

The schema doc leaves `operation_type` / `status` / `change_type`
vocabularies unspecified — the enums below are this implementation's
fill-in, extendable when Phase 12 adds tag edits and rollbacks.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class OperationType(StrEnum):
    FILE_MOVE = "file_move"


class OperationStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class ChangeType(StrEnum):
    MOVE = "move"


@dataclass(frozen=True, slots=True)
class Operation:
    """One mutating library operation, persisted in `operations`."""

    id: UUID
    operation_type: OperationType
    status: OperationStatus
    started_at: datetime
    is_dry_run: bool = False
    description: str | None = None
    affected_count: int = 0
    completed_at: datetime | None = None
    snapshot_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class ChangeRecord:
    """One tracked change belonging to an operation (`change_history`)."""

    id: UUID
    operation_id: UUID
    change_type: ChangeType
    timestamp: datetime
    track_id: UUID | None = None
    field_name: str | None = None
    old_value: str | None = None
    new_value: str | None = None
    old_file_path: str | None = None
    new_file_path: str | None = None
    old_zone: str | None = None
    new_zone: str | None = None
