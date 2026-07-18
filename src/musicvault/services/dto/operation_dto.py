"""DTOs for the OperationOrchestrator (Phase 12)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from musicvault.models.entities.operation import Operation, OperationType
from musicvault.models.entities.track import LibraryZone


@dataclass(frozen=True, slots=True)
class OperationRequest:
    """Input for :meth:`OperationOrchestrator.preview` / ``execute``.

    Only ``file_move`` is supported in Phase 12 — metadata tag rewrites
    stay deferred until a tag-write path exists.
    """

    operation_type: OperationType
    track_id: UUID
    target_zone: LibraryZone
    dry_run: bool = True


@dataclass(frozen=True, slots=True)
class OperationResult:
    """Outcome of preview / execute / rollback."""

    success: bool
    operation_id: UUID | None = None
    message: str | None = None
    affected_count: int = 0
    details: dict[str, Any] = field(default_factory=dict)
    operation: Operation | None = None
