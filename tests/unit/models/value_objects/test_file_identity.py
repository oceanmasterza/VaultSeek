"""Unit tests for vaultseek.models.value_objects.file_identity."""

from __future__ import annotations

from datetime import UTC, datetime

from vaultseek.db.uuid_utils import generate_uuid7
from vaultseek.models.value_objects.file_identity import FileIdentity

_MODIFIED = datetime(2026, 7, 15, tzinfo=UTC)


def _make_identity(**overrides: object) -> FileIdentity:
    defaults: dict[str, object] = {
        "track_id": generate_uuid7(),
        "content_hash_sha256": "a" * 64,
        "file_size": 1024,
        "file_modified": _MODIFIED,
    }
    defaults.update(overrides)
    return FileIdentity(**defaults)  # type: ignore[arg-type]


def test_file_identity_applies_documented_defaults() -> None:
    identity = _make_identity()

    assert identity.fingerprint_data is None
    assert identity.fingerprint_duration is None
    assert identity.fingerprint_hash is None
    assert identity.acoustid_id is None
    assert identity.acoustid_score is None
    assert identity.hash_computed_at is None
    assert identity.fingerprint_computed_at is None


def test_matches_current_file_true_when_size_and_modified_unchanged() -> None:
    identity = _make_identity(file_size=2048, file_modified=_MODIFIED)

    assert identity.matches_current_file(file_size=2048, file_modified=_MODIFIED) is True


def test_matches_current_file_false_when_size_changed() -> None:
    identity = _make_identity(file_size=2048, file_modified=_MODIFIED)

    assert identity.matches_current_file(file_size=4096, file_modified=_MODIFIED) is False


def test_matches_current_file_false_when_modified_changed() -> None:
    identity = _make_identity(file_size=2048, file_modified=_MODIFIED)
    later = datetime(2026, 7, 16, tzinfo=UTC)

    assert identity.matches_current_file(file_size=2048, file_modified=later) is False
