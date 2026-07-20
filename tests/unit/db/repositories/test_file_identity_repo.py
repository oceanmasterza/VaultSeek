"""Unit tests for vaultseek.db.repositories.file_identity_repo.FileIdentityRepository."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Engine

from vaultseek.db.repositories.file_identity_repo import FileIdentityRepository
from vaultseek.db.uuid_utils import generate_uuid7
from vaultseek.models.value_objects.file_identity import FileIdentity

_NOW = datetime(2026, 7, 15, tzinfo=UTC)


def _make_identity(track_id: UUID, **overrides: object) -> FileIdentity:
    defaults: dict[str, object] = {
        "track_id": track_id,
        "content_hash_sha256": "a" * 64,
        "file_size": 1024,
        "file_modified": _NOW,
    }
    defaults.update(overrides)
    return FileIdentity(**defaults)  # type: ignore[arg-type]


def test_upsert_and_get_round_trips_every_field(engine: Engine, track_id: UUID) -> None:
    repo = FileIdentityRepository(engine)
    identity = _make_identity(
        track_id,
        fingerprint_data=b"\x00\x01\x02",
        fingerprint_duration=180.5,
        fingerprint_hash="deadbeef",
        acoustid_id="acoustid-123",
        acoustid_score=0.97,
        hash_computed_at=_NOW,
        fingerprint_computed_at=_NOW,
    )

    repo.upsert(identity)
    loaded = repo.get(track_id)

    assert loaded == identity


def test_get_returns_none_for_missing_identity(engine: Engine) -> None:
    repo = FileIdentityRepository(engine)

    assert repo.get(generate_uuid7()) is None


def test_upsert_overwrites_existing_identity_for_same_track(engine: Engine, track_id: UUID) -> None:
    repo = FileIdentityRepository(engine)
    repo.upsert(_make_identity(track_id, content_hash_sha256="a" * 64))

    repo.upsert(_make_identity(track_id, content_hash_sha256="b" * 64))

    loaded = repo.get(track_id)
    assert loaded is not None
    assert loaded.content_hash_sha256 == "b" * 64


def test_matches_current_file_reflects_stored_size_and_mtime(
    engine: Engine, track_id: UUID
) -> None:
    repo = FileIdentityRepository(engine)
    identity = _make_identity(track_id, file_size=2048, file_modified=_NOW)
    repo.upsert(identity)

    loaded = repo.get(track_id)

    assert loaded is not None
    assert loaded.matches_current_file(file_size=2048, file_modified=_NOW)
    assert not loaded.matches_current_file(file_size=999, file_modified=_NOW)


def test_to_row_matches_what_upsert_persists(engine: Engine, track_id: UUID) -> None:
    repo = FileIdentityRepository(engine)
    identity = _make_identity(track_id)

    row = FileIdentityRepository.to_row(identity)

    assert row["track_id"] == track_id.bytes
    assert row["content_hash_sha256"] == identity.content_hash_sha256
    repo.upsert(identity)
    assert repo.get(track_id) == identity
