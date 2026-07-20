"""Unit tests for vaultseek.models.entities.artist."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

import pytest

from vaultseek.db.uuid_utils import generate_uuid7
from vaultseek.models.entities.artist import Artist

_NOW = datetime(2026, 7, 15, tzinfo=UTC)


def _make_artist(**overrides: object) -> Artist:
    defaults: dict[str, object] = {
        "id": generate_uuid7(),
        "name": "Allen Watts",
        "sort_name": "Watts, Allen",
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    defaults.update(overrides)
    return Artist(**defaults)  # type: ignore[arg-type]


def test_artist_applies_documented_defaults() -> None:
    artist = _make_artist()

    assert artist.mbid is None
    assert artist.discogs_id is None
    assert artist.type is None
    assert artist.country is None


def test_artist_is_immutable() -> None:
    artist = _make_artist()

    with pytest.raises(dataclasses.FrozenInstanceError):
        artist.name = "New Name"  # type: ignore[misc]


def test_artist_accepts_full_metadata() -> None:
    artist = _make_artist(mbid="mbid-456", type="Person", country="NL")

    assert artist.mbid == "mbid-456"
    assert artist.type == "Person"
    assert artist.country == "NL"
