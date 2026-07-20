"""Unit tests for vaultseek.models.entities.album."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

import pytest

from vaultseek.db.uuid_utils import generate_uuid7
from vaultseek.models.entities.album import Album

_NOW = datetime(2026, 7, 15, tzinfo=UTC)


def _make_album(**overrides: object) -> Album:
    defaults: dict[str, object] = {
        "id": generate_uuid7(),
        "title": "Indicator",
        "sort_title": "Indicator",
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    defaults.update(overrides)
    return Album(**defaults)  # type: ignore[arg-type]


def test_album_applies_documented_defaults() -> None:
    album = _make_album()

    assert album.album_artist_id is None
    assert album.year is None
    assert album.disc_count == 1
    assert album.track_count == 0
    assert album.is_compilation is False


def test_album_is_immutable() -> None:
    album = _make_album()

    with pytest.raises(dataclasses.FrozenInstanceError):
        album.title = "New Title"  # type: ignore[misc]


def test_album_accepts_full_release_metadata() -> None:
    album = _make_album(
        album_artist_id=generate_uuid7(),
        year=2024,
        mbid="mbid-123",
        type="Album",
        disc_count=2,
        track_count=20,
        is_compilation=True,
    )

    assert album.year == 2024
    assert album.type == "Album"
    assert album.disc_count == 2
    assert album.is_compilation is True
