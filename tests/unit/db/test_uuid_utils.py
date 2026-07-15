"""Unit tests for musicvault.db.uuid_utils."""

from __future__ import annotations

from uuid import UUID

import pytest

from musicvault.db.uuid_utils import blob_to_uuid, generate_uuid7, uuid_to_blob


def test_generate_uuid7_returns_version_7_uuid() -> None:
    value = generate_uuid7()

    assert value.version == 7


def test_generate_uuid7_returns_unique_values_across_calls() -> None:
    values = {generate_uuid7() for _ in range(1000)}

    assert len(values) == 1000


def test_generate_uuid7_values_are_time_ordered() -> None:
    values = [generate_uuid7() for _ in range(1000)]

    assert values == sorted(values)


def test_uuid_to_blob_returns_16_bytes() -> None:
    value = generate_uuid7()

    blob = uuid_to_blob(value)

    assert isinstance(blob, bytes)
    assert len(blob) == 16


def test_blob_to_uuid_round_trips_uuid_to_blob() -> None:
    original = generate_uuid7()

    restored = blob_to_uuid(uuid_to_blob(original))

    assert restored == original


def test_blob_to_uuid_rejects_short_blob() -> None:
    with pytest.raises(ValueError, match="16 bytes"):
        blob_to_uuid(b"\x00" * 8)


def test_blob_to_uuid_rejects_long_blob() -> None:
    with pytest.raises(ValueError, match="16 bytes"):
        blob_to_uuid(b"\x00" * 20)


def test_uuid_to_blob_is_reversible_for_a_known_uuid() -> None:
    known = UUID("019f6467-189f-7141-a2c3-3ea562b7ff41")

    assert blob_to_uuid(uuid_to_blob(known)) == known
