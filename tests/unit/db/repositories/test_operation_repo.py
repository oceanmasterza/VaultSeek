"""Unit tests for vaultseek.db.repositories.operation_repo."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import Engine

from vaultseek.db.repositories.operation_repo import OperationRepository
from vaultseek.db.uuid_utils import generate_uuid7
from vaultseek.models.entities.operation import (
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


def test_record_with_snapshot_links_operation_and_snapshot(
    repo: OperationRepository, track_id: UUID
) -> None:
    from vaultseek.db.repositories.operation_repo import (
        build_move_snapshot_payload,
        decode_snapshot_data,
        encode_snapshot_data,
    )
    from vaultseek.models.entities.operation import RollbackSnapshot

    operation_id = generate_uuid7()
    snapshot_id = generate_uuid7()
    change = _change(operation_id, track_id)
    operation = _operation(id=operation_id, snapshot_id=snapshot_id)
    snapshot = RollbackSnapshot(
        id=snapshot_id,
        operation_id=operation_id,
        snapshot_data=encode_snapshot_data(build_move_snapshot_payload([change])),
        created_at=_NOW,
    )

    repo.record_with_snapshot(operation, [change], snapshot)

    loaded = repo.get(operation_id)
    assert loaded is not None
    assert loaded.snapshot_id == snapshot_id
    stored = repo.get_snapshot(snapshot_id)
    assert stored is not None
    assert stored.operation_id == operation_id
    payload = decode_snapshot_data(stored.snapshot_data)
    assert payload["version"] == 1
    assert payload["changes"][0]["old_zone"] == "incoming"
    assert repo.get_snapshot_for_operation(operation_id) == stored


def test_list_recent_returns_newest_first(repo: OperationRepository) -> None:
    older = _operation(started_at=datetime(2026, 7, 16, tzinfo=UTC))
    newer = _operation(started_at=datetime(2026, 7, 17, tzinfo=UTC))
    repo.record(older, [])
    repo.record(newer, [])

    recent = repo.list_recent(limit=10)

    assert [op.id for op in recent[:2]] == [newer.id, older.id]


def test_set_status_and_mark_snapshot_restored(repo: OperationRepository, track_id: UUID) -> None:
    from vaultseek.db.repositories.operation_repo import (
        build_move_snapshot_payload,
        encode_snapshot_data,
    )
    from vaultseek.models.entities.operation import RollbackSnapshot

    operation_id = generate_uuid7()
    snapshot_id = generate_uuid7()
    change = _change(operation_id, track_id)
    repo.record_with_snapshot(
        _operation(id=operation_id, snapshot_id=snapshot_id),
        [change],
        RollbackSnapshot(
            id=snapshot_id,
            operation_id=operation_id,
            snapshot_data=encode_snapshot_data(build_move_snapshot_payload([change])),
            created_at=_NOW,
        ),
    )

    restored_at = datetime(2026, 7, 18, tzinfo=UTC)
    repo.set_status(operation_id, OperationStatus.ROLLED_BACK, completed_at=restored_at)
    repo.mark_snapshot_restored(snapshot_id, restored_at)

    assert repo.get(operation_id).status is OperationStatus.ROLLED_BACK  # type: ignore[union-attr]
    assert repo.get_snapshot(snapshot_id).restored_at == restored_at  # type: ignore[union-attr]
