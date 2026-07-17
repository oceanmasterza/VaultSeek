"""Unit tests for musicvault.db.repositories.operation_repo."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import Engine

from musicvault.db.repositories.operation_repo import OperationRepository
from musicvault.db.uuid_utils import generate_uuid7
from musicvault.models.entities.operation import (
    ChangeRecord,
    ChangeType,
    Operation,
    OperationStatus,
    OperationType,
)

_NOW = datetime(2026, 7, 17, tzinfo=UTC)


@pytest.fixture
def repo(engine: Engine) -> OperationRepository:
    return OperationRepository(engine)


def _operation(**overrides: object) -> Operation:
    defaults: dict[str, object] = {
        "id": generate_uuid7(),
        "operation_type": OperationType.FILE_MOVE,
        "status": OperationStatus.COMPLETED,
        "started_at": _NOW,
        "completed_at": _NOW,
        "affected_count": 1,
        "description": "Moved 'x.flac' from incoming to staging",
    }
    defaults.update(overrides)
    return Operation(**defaults)  # type: ignore[arg-type]


def _change(operation_id: UUID, track_id: UUID | None = None) -> ChangeRecord:
    return ChangeRecord(
        id=generate_uuid7(),
        operation_id=operation_id,
        change_type=ChangeType.MOVE,
        timestamp=_NOW,
        track_id=track_id,
        old_file_path="C:/incoming/x.flac",
        new_file_path="C:/staging/Artist/x.flac",
        old_zone="incoming",
        new_zone="staging",
    )


def test_record_round_trips_operation_and_changes(
    repo: OperationRepository, track_id: UUID
) -> None:
    operation = _operation()
    change = _change(operation.id, track_id)

    repo.record(operation, [change])

    assert repo.get(operation.id) == operation
    assert repo.list_changes(operation.id) == [change]


def test_get_returns_none_for_unknown_operation(repo: OperationRepository) -> None:
    assert repo.get(generate_uuid7()) is None


def test_record_accepts_an_operation_without_changes(repo: OperationRepository) -> None:
    operation = _operation(affected_count=0)

    repo.record(operation, [])

    assert repo.get(operation.id) == operation
    assert repo.list_changes(operation.id) == []


def test_list_changes_for_track_orders_by_timestamp(
    repo: OperationRepository, track_id: UUID
) -> None:
    first_op = _operation(started_at=_NOW, completed_at=_NOW)
    second_op = _operation()
    first = ChangeRecord(
        id=generate_uuid7(),
        operation_id=first_op.id,
        change_type=ChangeType.MOVE,
        timestamp=datetime(2026, 7, 16, tzinfo=UTC),
        track_id=track_id,
        old_zone="incoming",
        new_zone="staging",
    )
    second = ChangeRecord(
        id=generate_uuid7(),
        operation_id=second_op.id,
        change_type=ChangeType.MOVE,
        timestamp=datetime(2026, 7, 17, tzinfo=UTC),
        track_id=track_id,
        old_zone="staging",
        new_zone="library",
    )
    repo.record(second_op, [second])
    repo.record(first_op, [first])

    history = repo.list_changes_for_track(track_id)

    assert [change.new_zone for change in history] == ["staging", "library"]
