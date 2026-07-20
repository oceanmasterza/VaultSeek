"""Operation / ChangeRecord / RollbackSnapshot entities — audit + restore.

Mirror the `operations`, `change_history`, and `rollback_snapshots`
tables (see docs/architecture/03-database-schema.md, "Operations &
Rollback"). Phase 10 wrote operations without snapshots; Phase 12
attaches a compressed JSON snapshot to every new mutating operation and
can reverse completed ``file_move`` operations via
:class:`~vaultseek.services.operation_orchestrator.OperationOrchestrator`.

The schema doc leaves `operation_type` / `status` / `change_type`
vocabularies unspecified — the enums below are this implementation's
fill-in. Only ``FILE_MOVE`` / ``MOVE`` are reversible today; metadata
tag rewrites stay deferred until a tag-write path exists.
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


@dataclass(frozen=True, slots=True)
class RollbackSnapshot:
    """Compressed pre-mutation state for one operation (`rollback_snapshots`).

    ``snapshot_data`` is the *decompressed* JSON document (gzip is applied
    at the repository boundary). Schema version 1 stores the list of
    change payloads the orchestrator needs to reverse a ``file_move``.
    """

    id: UUID
    operation_id: UUID
    snapshot_data: bytes
    created_at: datetime
    restored_at: datetime | None = None
